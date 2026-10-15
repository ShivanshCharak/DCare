import test from "node:test";
import assert from "node:assert/strict";
import { checkFailureDescription, checkPurpose, meaningfulReasons, reasonDescription, verificationRows, verificationDetailMessage, claimOverviewCounts } from "../app/utils.ts";

test("all 15 verification categories render and retain supplied statuses", () => {
  const input = Object.fromEntries(
    ["source_ids", "fact_extraction", "exact_match", "risk_rules", "ambiguous_medication_details", "medication_names", "medication_context", "high_alert_medication", "unsupported_details", "numeric_details", "instruction_polarity", "medication_contradictions", "entailment_judge", "back_translation", "translation"].map((name) => [name, "passed"]),
  );
  const rows = verificationRows(input);
  assert.equal(rows.length, 15);
  assert.ok(rows.every(([, status]) => status === "passed"));
});

test("verification rows include only checks with returned statuses", () => {
  const rows = verificationRows({ risk_rules: "review_suggested", back_translation: "not_configured" });
  assert.equal(rows.length, 2);
  assert.equal(rows.find(([name]) => name === "risk_rules")?.[1], "review_suggested");
  assert.equal(rows.find(([name]) => name === "back_translation")?.[1], "not_configured");
  assert.equal(rows.find(([name]) => name === "source_ids"), undefined);
  assert.equal(verificationRows(null).length, 0);
});

test("not applicable checks are omitted from the verification list", () => {
  const rows = verificationRows({ risk_rules: "not_applicable", back_translation: "not_configured" });
  assert.equal(rows.length, 1);
  assert.equal(rows.find(([name]) => name === "risk_rules"), undefined);
  assert.equal(rows.find(([name]) => name === "back_translation")?.[1], "not_configured");
});

test("empty and placeholder review reasons are removed", () => {
  assert.deepEqual(meaningfulReasons(["-", "", null, "  ", {}, "risk", "risk"] as any), ["risk"]);
  assert.deepEqual(meaningfulReasons(null), []);
  assert.match(reasonDescription("unmapped_reason"), /compare the generated explanation/);
});

test("every verification category has a useful purpose description", () => {
  const names = verificationRows(Object.fromEntries(
    ["source_ids", "fact_extraction", "exact_match", "risk_rules", "ambiguous_medication_details", "medication_names", "medication_context", "high_alert_medication", "unsupported_details", "numeric_details", "instruction_polarity", "medication_contradictions", "entailment_judge", "back_translation", "translation"].map((name) => [name, "passed"]),
  )).map(([name]) => name);
  assert.ok(names.every((name) => checkPurpose(name).length > 20));
  assert.match(checkPurpose("exact_match"), /does not establish clinical safety/);
  assert.match(checkPurpose("warning_sign_urgency"), /response level/);
});

test("checks without optional detail messages still show a finding", () => {
  assert.match(checkFailureDescription("source_ids", "passed") ?? "", /found no issue/);
  assert.match(checkFailureDescription("risk_rules", "not_applicable") ?? "", /does not apply/);
  assert.match(checkFailureDescription("back_translation", "not_configured") ?? "", /did not run/);
});

test("exact wording differences are informational rather than failed checks", () => {
  assert.match(checkFailureDescription("exact_match", "informational") ?? "", /does not count as a verification failure/);
  assert.equal(reasonDescription("unsupported_medication_context").includes("source does not state"), true);
});

test("C1-C4 claim categories retain actual check statuses and render sparse details safely", () => {
  const categories = ["diagnosis", "medication", "appointment", "warning_sign"];
  const responses = categories.map((kind, index) => ({
    id: `C${index + 1}`,
    kind,
    checks: { source_ids: "passed", risk_rules: index === 1 ? "failed" : "not_applicable" },
    check_details: index < 2
      ? { source_ids: { name: "source_ids", status: "passed", message: "Source links are valid." } }
      : {},
  }));
  assert.deepEqual(responses.map(({ checks }) => verificationRows(checks).find(([name]) => name === "risk_rules")?.[1]), [undefined, "failed", undefined, undefined]);
  assert.equal(verificationDetailMessage(responses[2].check_details.source_ids, "source_ids", "passed"), "This check ran and found no issue in the information it evaluates. It does not establish clinical correctness by itself.");
  assert.equal(verificationDetailMessage({ message: "  " }, "source_ids", null), "No status or additional details were returned for this check.");
  assert.equal(verificationDetailMessage("Legacy detail", "source_ids", "passed"), "Legacy detail");
  assert.equal(verificationRows({ custom_check: "review_suggested" }).find(([name]) => name === "custom_check")?.[1], "review_suggested");
});

test("overview counts follow claim states without promoting incomplete checks", () => {
  assert.deepEqual(claimOverviewCounts([
    { state: "needs_clinician" }, { state: "review_suggested" },
    { state: "verified" }, { state: "review_suggested" }, { state: "source_supported" },
  ]), { needsClinician: 1, reviewSuggested: 2, sourceSupported: 1, verified: 1 });
});
