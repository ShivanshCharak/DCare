type QuestionsListProps = {
  questions: string[];
};

export function QuestionsList({ questions }: QuestionsListProps) {
  if (questions.length === 0) {
    return null;
  }

  return (
    <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
      <h2 className="text-xl font-bold text-slate-950">
        5. Questions to ask your clinician
      </h2>

      <ul className="mt-4 list-disc space-y-3 pl-6 text-sm leading-6 text-slate-700">
        {questions.map((question, index) => (
          <li key={`${index}-${question}`}>{question}</li>
        ))}
      </ul>
    </section>
  );
}
