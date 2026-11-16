import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { UserChoicePromptV1 } from "../contracts/generated/bridge";

export interface ChoiceAnswer {
  readonly questionId: string;
  readonly optionId: string;
  readonly notes: string;
  readonly status?: "accepted" | "unknown" | "rejected";
  readonly executionId?: string;
}

export function UserChoiceCard({ question, answer, enabled, onChange, onConfirm }: {
  question: UserChoicePromptV1;
  answer?: ChoiceAnswer;
  enabled: boolean;
  onChange: (answer: ChoiceAnswer) => void;
  onConfirm: (text: string, answer: ChoiceAnswer) => void;
}) {
  const { t } = useTranslation("session");
  const group = useId();
  const { optionId = "", notes = "", status } = answer ?? {};
  const selected = question.options.find((option) => option.id === optionId);
  const editable = enabled && status !== "unknown" && status !== "accepted";

  return <form className="user-choice" aria-label={t("choice.title")} onSubmit={(event) => {
    event.preventDefault();
    if (!editable || !selected) return;
    const parts: string[] = [t("choice.answer", { question: question.question, id: selected.id, label: selected.label })];
    if (notes.trim()) parts.push(t("choice.answerNotes", { notes: notes.trim() }));
    onConfirm(parts.join("\n"), { questionId: question.questionId, optionId, notes });
  }}>
    <fieldset disabled={!editable}>
      <legend>{question.question}</legend>
      {question.options.map((option) => <label className="choice-option" key={option.id}>
        <input type="radio" name={group} checked={option.id === optionId}
          onChange={() => onChange({ questionId: question.questionId, optionId: option.id, notes })} />
        <span>{option.label}{option.description && <small>{option.description}</small>}</span>
      </label>)}
      <label className="choice-notes">{t("choice.notes")}
        <input value={notes} maxLength={1024}
          onChange={(event) => onChange({ questionId: question.questionId, optionId, notes: event.target.value })} />
      </label>
      <button type="submit" disabled={!selected}>{t("choice.confirm")}</button>
    </fieldset>
    {status && <p role="status">{t(`choice.${status}`)}</p>}
  </form>;
}
