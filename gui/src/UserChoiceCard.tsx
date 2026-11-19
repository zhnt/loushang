import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { UserChoicePromptV1 } from "../contracts/generated/bridge";
import { UiIcon } from "./UiIcon";

export interface ChoiceAnswer {
  readonly questionId: string;
  readonly optionId: string;
  readonly notes: string;
  readonly status?: "accepted" | "unknown" | "rejected";
  readonly executionId?: string;
}

export function UserChoiceCard({ question, answer, enabled, onChange, onConfirm, anchorId }: {
  anchorId?: string;
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
  const editable = enabled && status !== "unknown";

  if (status === "accepted" && selected) {
    return <ChoiceReceipt label={selected.label} text={[question.question, notes.trim()].filter(Boolean).join("\n")} />;
  }

  return <form className="user-choice" id={anchorId} tabIndex={anchorId ? -1 : undefined} aria-label={t("choice.title")} onSubmit={(event) => {
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
      <button type="submit" className="primary-button" disabled={!selected}>{t("choice.confirm")}</button>
    </fieldset>
    {status && <p role="status">{t(`choice.${status}`)}</p>}
  </form>;
}

export function ChoiceReceipt({ label, text }: { readonly label: string; readonly text: string }) {
  const { t } = useTranslation("session");
  return <details className="choice-receipt">
    <summary><UiIcon name="chevron-down" /><span>{t("choice.selected")} · {label}</span></summary>
    <p>{text}</p>
  </details>;
}

export function submittedChoiceLabel(text: string): string | undefined {
  // Existing sessions store the localized answer as ordinary user input.
  const english = /^Question: [\s\S]+?\nSelected option [\w.~\-]+: ([^\n]+)(?:\nAdditional notes: [\s\S]+)?$/u;
  const chinese = /^问题：[\s\S]+?\n已选选项 [\w.~\-]+：([^\n]+)(?:\n补充说明：[\s\S]+)?$/u;
  return (english.exec(text) ?? chinese.exec(text))?.[1];
}
