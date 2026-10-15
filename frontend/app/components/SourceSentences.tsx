import type { DocumentRecord } from "../types";

type SourceSentencesProps = {
  doc: DocumentRecord;
  selectedSource: string | null;
  onSelectSource: (sourceId: string) => void;
};

export function SourceSentences({
  doc,
  selectedSource,
  onSelectSource,
}: SourceSentencesProps) {
  const coveredSourceIds = new Set(doc.claims.flatMap((claim) => claim.source_ids));
  const contextOnlyCount = doc.sentences.filter((sentence) => !coveredSourceIds.has(sentence.id)).length;
  return (
    <div className="source-panel rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
      <div className="source-panel-heading"><div><p className="option-kicker">ORIGINAL DOCUMENT</p><h2 className="mt-1 text-xl font-bold text-slate-950">Source note</h2></div><span className="source-count">{doc.sentences.length} sentences</span></div>

      <p className="mb-5 mt-2 text-sm leading-6 text-slate-600">
        Choose a source label on an explanation to jump to its original wording. Source text without an extracted clinical fact stays visible as context.
      </p>

      {contextOnlyCount > 0 && <div role="status" className="mb-4 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        {contextOnlyCount} {contextOnlyCount === 1 ? "sentence has" : "sentences have"} no linked clinical fact. Sentences without a linked fact appear in the reviewer queue; headings and document identifiers remain context.
      </div>}

      {doc.sentences.map((sentence) => (
        <article
          key={sentence.id}
          id={`source-${sentence.id}`}
          role="button"
          tabIndex={0}
          aria-pressed={selectedSource === sentence.id}
          onClick={() => onSelectSource(sentence.id)}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelectSource(sentence.id); } }}
          className={`source-sentence-card mb-3 cursor-pointer scroll-mt-6 rounded-lg border p-3 transition ${
            selectedSource === sentence.id
              ? "border-blue-400 bg-blue-50 ring-2 ring-blue-100"
              : "border-slate-200 bg-slate-50"
          }`}
        >
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-500">
              {sentence.id}
            </span>

            <span className="rounded-full bg-white px-2 py-1 text-xs text-slate-500">
              {sentence.section.replaceAll("_", " ")}
            </span>
            {!coveredSourceIds.has(sentence.id) && <span className="rounded-full border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-600">No clinical fact extracted</span>}
          </div>

          <p className="text-sm leading-6 text-slate-800">{sentence.text}</p>
        </article>
      ))}
    </div>
  );
}
