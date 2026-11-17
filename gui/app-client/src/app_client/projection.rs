//! Closed execution snapshot and content/metadata-event wire projection.
use super::identifier;
use serde::{Deserialize, Serialize};
use serde_json::{value::RawValue, Value};
use std::collections::BTreeSet;

#[derive(Deserialize, Serialize)]
#[serde(try_from = "Box<RawValue>")]
struct Counter(String);
impl TryFrom<Box<RawValue>> for Counter {
    type Error = &'static str;
    fn try_from(raw: Box<RawValue>) -> Result<Self, Self::Error> {
        let text = raw.get();
        if text.is_empty()
            || !text.bytes().all(|c| c.is_ascii_digit())
            || (text.len() > 1 && text.starts_with('0'))
        {
            return Err("invalid counter");
        }
        Ok(Self(text.to_owned()))
    }
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Envelope<T> {
    protocol_version: String,
    request_id: String,
    result_type: String,
    result: T,
}
#[derive(Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Identity {
    product_id: String,
    continuity_id: String,
    session_id: String,
    scope: String,
    scope_fingerprint: String,
}
impl Identity {
    fn valid(&self) -> bool {
        identifier(&self.product_id, 128)
            && self
                .product_id
                .bytes()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"._-".contains(&c))
            && identifier(&self.continuity_id, 512)
            && identifier(&self.session_id, 512)
            && ["cwd", "user_home"].contains(&self.scope.as_str())
            && self.scope_fingerprint.len() == 64
            && self
                .scope_fingerprint
                .bytes()
                .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Record {
    kind: String,
    text: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Source {
    #[serde(
        default,
        rename = "submissionMode",
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    submission_mode: Option<SubmissionMode>,
    #[serde(
        default,
        rename = "userChoice",
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    user_choice: Option<UserChoicePrompt>,
    identity: Identity,
    title: String,
    cursor: Counter,
    revision: Counter,
    running: bool,
    records: Vec<Record>,
}
// The reference codec permits omission or exactly "execution", never null/legacy.
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum SubmissionMode {
    Execution,
}
fn present<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> Result<Option<T>, D::Error> {
    T::deserialize(deserializer).map(Some)
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct UserChoicePrompt {
    question_id: String,
    question: String,
    options: Vec<UserChoiceOption>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct UserChoiceOption {
    id: String,
    label: String,
    description: Box<RawValue>,
}

impl UserChoicePrompt {
    fn valid(&self) -> bool {
        let mut ids = BTreeSet::new();
        identifier(&self.question_id, 512)
            && choice_text(&self.question, 1024)
            && (2..=5).contains(&self.options.len())
            && self.options.iter().all(|option| {
                identifier(&option.id, 64)
                    && ids.insert(&option.id)
                    && choice_text(&option.label, 160)
                    && optional_string(&option.description)
                        .is_ok_and(|value| value.is_none_or(|text| choice_text(&text, 512)))
            })
    }
}

fn choice_text(text: &str, limit: usize) -> bool {
    !text.trim().is_empty() && text.chars().count() <= limit
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Observation {
    execution_id: Box<RawValue>,
    status: Box<RawValue>,
    final_cursor: Box<RawValue>,
}
impl Observation {
    fn valid(&self) -> bool {
        let (Ok(id), Ok(status), Ok(final_cursor)) = (
            optional_string(&self.execution_id),
            optional_string(&self.status),
            self.watermark(),
        ) else {
            return false;
        };
        if let Some(id) = id {
            identifier(&id, 128)
                && status
                    .as_deref()
                    .is_some_and(|s| s == "running" || terminal(s))
                && (status.as_deref().is_some_and(terminal) == final_cursor.is_some())
        } else {
            status.is_none() && final_cursor.is_none()
        }
    }
    fn watermark(&self) -> Result<Option<u64>, ()> {
        let value: Option<u64> = serde_json::from_str(self.final_cursor.get()).map_err(|_| ())?;
        if value.is_some_and(|n| n > 9_007_199_254_740_991) {
            return Err(());
        }
        Ok(value)
    }
    fn running(&self) -> bool {
        optional_string(&self.status).is_ok_and(|s| s.as_deref() == Some("running"))
    }
    fn after(&self, cursor: &Counter) -> bool {
        self.watermark().ok().flatten().is_some_and(|n| {
            let end = n.to_string();
            cursor.0.len() < end.len() || (cursor.0.len() == end.len() && cursor.0 < end)
        })
    }
}
fn terminal(status: &str) -> bool {
    ["succeeded", "failed", "interrupted"].contains(&status)
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct State {
    execution_id: String,
    status: String,
    revision: u64,
    interrupt_requested: bool,
    outcome: Box<RawValue>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Outcome {
    status: String,
    error_code: Box<RawValue>,
    legacy_result: Box<RawValue>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LegacyFailure {
    code: String,
}
impl State {
    fn valid(&self) -> bool {
        if !identifier(&self.execution_id, 128) || self.revision > 9_007_199_254_740_991 {
            return false;
        }
        if !terminal(&self.status) {
            return ["accepted", "running"].contains(&self.status.as_str())
                && self.outcome.get() == "null";
        }
        let Ok(outcome) = serde_json::from_str::<Outcome>(self.outcome.get()) else {
            return false;
        };
        let Ok(error) = optional_string(&outcome.error_code) else {
            return false;
        };
        if outcome.status != self.status
            || (self.status == "failed") != error.is_some()
            || error.is_some_and(|s| !identifier(&s, 128))
        {
            return false;
        }
        if serde_json::from_str::<std::collections::BTreeMap<String, Value>>(
            outcome.legacy_result.get(),
        )
        .is_ok_and(|m| m.is_empty())
        {
            return true;
        }
        serde_json::from_str::<LegacyFailure>(outcome.legacy_result.get())
            .is_ok_and(|v| APP_ERROR_CODES.contains(&v.code.as_str()))
    }
}
const APP_ERROR_CODES: &[&str] = &[
    "invalid_request",
    "not_found",
    "already_exists",
    "already_attached",
    "product_mismatch",
    "revision_conflict",
    "snapshot_required",
    "stale_attachment",
    "attachment_lagged",
    "session_unavailable",
    "operation_unavailable",
    "permission_denied",
    "workspace_preview_binary",
    "workspace_preview_too_large",
    "workspace_registration_failed",
    "cleanup_incomplete",
    "service_closed",
];

fn state_slot(raw: &RawValue, is_terminal: bool) -> bool {
    raw.get() == "null"
        || serde_json::from_str::<State>(raw.get())
            .is_ok_and(|v| v.valid() && terminal(&v.status) == is_terminal)
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Update {
    revision: u64,
    execution: State,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SourceSnapshot {
    source: Source,
    observation: Observation,
    draft: String,
    truncated: bool,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct View {
    identity: Identity,
    revision: u64,
    quiescent: Observation,
    active: Box<RawValue>,
    latest_terminal: Box<RawValue>,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Snapshot {
    service_instance_id: String,
    source: SourceSnapshot,
    executions: View,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    supports_goal_progress: Option<bool>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    supports_goal_start: Option<bool>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    supports_interactive_goal: Option<bool>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    supports_interactive_goal_commands: Option<bool>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    supports_interactive_goal_recovery: Option<bool>,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordEnvelope {
    service_instance_id: String,
    identity: Identity,
    submission_id: Box<RawValue>,
    state: State,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct InterruptResult {
    record: RecordEnvelope,
    disposition: String,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Failure {
    code: String,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Event {
    session_id: String,
    cursor: Counter,
    kind: String,
    text: Box<RawValue>,
    interaction_id: Box<RawValue>,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Content {
    source: Event,
    execution_id: Box<RawValue>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Events {
    events: Vec<Box<RawValue>>,
}
fn optional_string(raw: &RawValue) -> Result<Option<String>, ()> {
    serde_json::from_str(raw.get()).map_err(|_| ())
}
fn envelope<T>(e: &Envelope<T>, kind: &str) -> bool {
    e.protocol_version == "loushang.execution/v1"
        && e.result_type == kind
        && identifier(&e.request_id, 128)
}
pub fn bridge(kind: &str, wire: &str) -> Result<Value, ()> {
    if kind == "snapshot" {
        let e: Envelope<Snapshot> = serde_json::from_str(wire).map_err(|_| ())?;
        let s = &e.result.source.source;
        let view = &e.result.executions;
        if !envelope(&e, kind)
            || e.result.supports_goal_progress == Some(false)
            || e.result.supports_goal_start == Some(false)
            || e.result.supports_interactive_goal == Some(false)
            || e.result.supports_interactive_goal_commands == Some(false)
            || e.result.supports_interactive_goal_recovery == Some(false)
            || (e.result.supports_interactive_goal_commands == Some(true)
                && e.result.supports_interactive_goal != Some(true))
            || !identifier(&e.result.service_instance_id, 128)
            || !s.identity.valid()
            || s.user_choice.as_ref().is_some_and(|choice| !choice.valid())
            || !view.identity.valid()
            || s.identity != view.identity
            || s.title.trim().is_empty()
            || s.title.chars().count() > 256
            || s.records.len() > 256
            || s.records
                .iter()
                .map(|r| r.text.chars().count())
                .sum::<usize>()
                > 65_536
            || s.records
                .iter()
                .any(|r| !["user", "assistant", "status", "error"].contains(&r.kind.as_str()))
            || !e.result.source.observation.valid()
            || e.result.source.draft.chars().count() > 16_384
            || (!e.result.source.draft.is_empty() && !e.result.source.observation.running())
            || e.result.source.observation.after(&s.cursor)
            || view.revision > 9_007_199_254_740_991
            || !view.quiescent.valid()
            || view.quiescent.running()
            || !state_slot(&view.active, false)
            || !state_slot(&view.latest_terminal, true)
        {
            return Err(());
        }
        serde_json::to_value(e).map_err(|_| ())
    } else {
        let e: Envelope<Events> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&e, "events") || e.result.events.len() > 256 {
            return Err(());
        }
        let mut projected = Vec::new();
        for raw in &e.result.events {
            if let Ok(update) = serde_json::from_str::<Update>(raw.get()) {
                if update.revision == 0
                    || update.revision > 9_007_199_254_740_991
                    || !update.execution.valid()
                {
                    return Err(());
                }
                projected.push(serde_json::to_value(update).map_err(|_| ())?);
                continue;
            }
            let content: Content = serde_json::from_str(raw.get()).map_err(|_| ())?;
            let s = &content.source;
            let text = optional_string(&s.text)?;
            let interaction = optional_string(&s.interaction_id)?;
            let execution = optional_string(&content.execution_id)?;
            if !identifier(&s.session_id, 512)
                || s.cursor.0 == "0"
                || ![
                    "turn_started",
                    "user_message",
                    "assistant_delta",
                    "assistant_message",
                    "status",
                    "error",
                    "turn_completed",
                    "turn_interrupted",
                    "interaction_requested",
                    "interaction_dismissed",
                ]
                .contains(&s.kind.as_str())
                || text.as_ref().is_some_and(|t| t.chars().count() > 262_144)
                || interaction.as_ref().is_some_and(|id| !identifier(id, 512))
                || execution.as_ref().is_some_and(|id| !identifier(id, 128))
                || ["interaction_requested", "interaction_dismissed"].contains(&s.kind.as_str())
                    != interaction.is_some()
            {
                return Err(());
            }
            projected.push(serde_json::to_value(content).map_err(|_| ())?);
        }
        Ok(
            serde_json::json!({"protocolVersion": e.protocol_version, "requestId": e.request_id,
            "resultType": e.result_type, "result": {"events": projected}}),
        )
    }
}

const MAX_GOAL_BATCHES: u64 = 16;

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GoalBatch {
    batch_id: String,
    work_status: Box<RawValue>,
    recording_available: bool,
    cancellation_status: Box<RawValue>,
    observation_unavailable: bool,
}

impl GoalBatch {
    fn valid(&self) -> Result<bool, ()> {
        Ok(identifier(&self.batch_id, 128)
            && optional_string(&self.work_status)?.is_none_or(|status| {
                [
                    "accepted",
                    "running",
                    "cancelling",
                    "completed",
                    "failed",
                    "cancelled",
                    "orphaned",
                ]
                .contains(&status.as_str())
            })
            && optional_string(&self.cancellation_status)?.is_none_or(|status| {
                [
                    "not_requested",
                    "pending",
                    "settled",
                    "unsupported",
                    "failed",
                    "unknown",
                ]
                .contains(&status.as_str())
            }))
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GoalProgress {
    execution_id: String,
    presence: String,
    goal_id: Box<RawValue>,
    status: Box<RawValue>,
    reason_code: String,
    validity: String,
    execution_unresolved: bool,
    advances: u64,
    model_calls: u64,
    batch_count: u64,
    batches: Vec<GoalBatch>,
}

impl GoalProgress {
    fn valid(&self) -> Result<bool, ()> {
        let goal_id = optional_string(&self.goal_id)?;
        let status = optional_string(&self.status)?;
        let identity = match self.presence.as_str() {
            "present" => {
                goal_id.is_some_and(|id| identifier(&id, 128))
                    && status.is_some_and(|value| {
                        [
                            "active",
                            "paused",
                            "completed",
                            "abandoned",
                            "failed",
                            "superseded",
                        ]
                        .contains(&value.as_str())
                    })
            }
            "not_started" | "initializing" | "unavailable" => goal_id.is_none() && status.is_none(),
            _ => false,
        };
        let reason = self.reason_code.as_bytes();
        Ok(identity
            && identifier(&self.execution_id, 128)
            && reason.len() <= 64
            && reason.first().is_some_and(u8::is_ascii_lowercase)
            && reason
                .iter()
                .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'_')
            && ["not_checked", "unknown"].contains(&self.validity.as_str())
            && [self.advances, self.model_calls, self.batch_count]
                .iter()
                .all(|count| *count <= 9_007_199_254_740_991)
            && self.valid_batches()?)
    }

    fn valid_batches(&self) -> Result<bool, ()> {
        if self.batches.len() as u64 != self.batch_count.min(MAX_GOAL_BATCHES) {
            return Ok(false);
        }
        let mut ids = BTreeSet::new();
        for batch in &self.batches {
            if !batch.valid()? || !ids.insert(&batch.batch_id) {
                return Ok(false);
            }
        }
        Ok(true)
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GoalCommandObservation {
    command_id: String,
    action: String,
    status: String,
}

impl GoalCommandObservation {
    fn valid(&self) -> bool {
        identifier(&self.command_id, 128)
            && match self.status.as_str() {
                "running" => {
                    ["run", "step", "resume", "accept", "reject"].contains(&self.action.as_str())
                }
                "settling" => ["pause", "cancel"].contains(&self.action.as_str()),
                "finished" | "failed" | "unknown" => [
                    "run", "step", "resume", "pause", "cancel", "accept", "reject",
                ]
                .contains(&self.action.as_str()),
                _ => false,
            }
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InteractiveGoal {
    availability: String,
    goal_id: Box<RawValue>,
    status: Box<RawValue>,
    revision: Box<RawValue>,
    epoch: Box<RawValue>,
    execution_unresolved: Box<RawValue>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    command: Option<GoalCommandObservation>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "present"
    )]
    review_available: Option<bool>,
}

impl InteractiveGoal {
    fn valid(&self) -> Result<bool, ()> {
        let goal_id = optional_string(&self.goal_id)?;
        let status = optional_string(&self.status)?;
        let revision: Option<u64> = serde_json::from_str(self.revision.get()).map_err(|_| ())?;
        let epoch: Option<u64> = serde_json::from_str(self.epoch.get()).map_err(|_| ())?;
        let unresolved: Option<bool> =
            serde_json::from_str(self.execution_unresolved.get()).map_err(|_| ())?;
        if let Some(available) = self.review_available {
            if !available
                || self.availability != "present"
                || status.as_deref() != Some("paused")
                || unresolved != Some(false)
                || self.command.as_ref().is_some_and(|value| {
                    ["running", "settling", "unknown"].contains(&value.status.as_str())
                })
            {
                return Ok(false);
            }
        }
        Ok(match self.availability.as_str() {
            "present" => {
                goal_id.is_some_and(|id| identifier(&id, 128))
                    && status.is_some_and(|value| {
                        [
                            "active",
                            "paused",
                            "completed",
                            "abandoned",
                            "failed",
                            "superseded",
                        ]
                        .contains(&value.as_str())
                    })
                    && [revision, epoch].into_iter().all(|count| {
                        count.is_some_and(|value| (1..=9_007_199_254_740_991).contains(&value))
                    })
                    && unresolved.is_some()
                    && self
                        .command
                        .as_ref()
                        .is_none_or(GoalCommandObservation::valid)
            }
            "ready" | "not_ready" | "creating" | "historical" | "cleanup_pending" => {
                goal_id.is_none()
                    && status.is_none()
                    && revision.is_none()
                    && epoch.is_none()
                    && unresolved.is_none()
                    && self.command.is_none()
            }
            _ => false,
        })
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InteractiveGoalReview {
    goal_id: String,
    revision: u64,
    epoch: u64,
    review_token: String,
    changed_files: Vec<String>,
    files_truncated: bool,
    check_count: u8,
    checks_satisfied: bool,
}

pub(super) fn review_token(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

fn review_path(value: &str) -> bool {
    value.len() <= 1024
        && value
            .split('/')
            .all(|part| !matches!(part, "" | "." | ".."))
        && value
            .bytes()
            .all(|c| c >= 32 && !matches!(c, b'\\' | b':' | 127))
}

impl InteractiveGoalReview {
    fn valid(&self) -> bool {
        identifier(&self.goal_id, 128)
            && review_token(&self.review_token)
            && [self.revision, self.epoch]
                .into_iter()
                .all(|n| (1..=9_007_199_254_740_991).contains(&n))
            && self.check_count <= 8
            && (self.check_count != 0 || self.checks_satisfied)
            && self.changed_files.len() <= 100
            && self.changed_files.iter().all(|path| review_path(path))
            && self.changed_files.iter().collect::<BTreeSet<_>>().len() == self.changed_files.len()
    }
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct InteractiveGoalRecovery {
    presence: String,
    reason_code: String,
    goal_id: Box<RawValue>,
    goal_status: Box<RawValue>,
    revision: Box<RawValue>,
    epoch: Box<RawValue>,
    batch_count: u64,
    completed_count: u64,
    failed_count: u64,
    cancelled_count: u64,
    orphaned_count: u64,
    execution_unresolved: bool,
    read_only: bool,
}

impl InteractiveGoalRecovery {
    fn valid(&self) -> Result<bool, ()> {
        const MAX: u64 = 9_007_199_254_740_991;
        let goal_id = optional_string(&self.goal_id)?;
        let status = optional_string(&self.goal_status)?;
        let revision: Option<u64> = serde_json::from_str(self.revision.get()).map_err(|_| ())?;
        let epoch: Option<u64> = serde_json::from_str(self.epoch.get()).map_err(|_| ())?;
        let work = [
            self.completed_count,
            self.failed_count,
            self.cancelled_count,
            self.orphaned_count,
        ];
        if !self.read_only
            || self.batch_count > MAX
            || work.iter().any(|&n| n > MAX)
            || work.iter().sum::<u64>() > self.batch_count
            || (self.orphaned_count > 0 && !self.execution_unresolved)
        {
            return Ok(false);
        }
        let reason = self.reason_code.as_str();
        if self.presence == "present" {
            return Ok(goal_id.is_some_and(|id| identifier(&id, 128))
                && status.is_some_and(|s| {
                    [
                        "active",
                        "paused",
                        "completed",
                        "abandoned",
                        "failed",
                        "superseded",
                    ]
                    .contains(&s.as_str())
                })
                && [revision, epoch]
                    .iter()
                    .all(|n| n.is_some_and(|n| (1..=MAX).contains(&n)))
                && [
                    "created",
                    "review_required",
                    "user_accepted_current_result",
                    "requirements_satisfied",
                    "user_pause",
                    "user_resume",
                    "user_review",
                    "user_cancel",
                    "run_interrupted",
                    "batch_limit",
                    "execution_unresolved",
                    "other",
                ]
                .contains(&reason));
        }
        if goal_id.is_some()
            || status.is_some()
            || revision.is_some()
            || epoch.is_some()
            || self.batch_count != 0
        {
            return Ok(false);
        }
        Ok(match self.presence.as_str() {
            "absent" => reason == "no_goal" && !self.execution_unresolved,
            "unavailable" => {
                self.execution_unresolved
                    && [
                        "source_changed",
                        "goal_journal_invalid",
                        "work_log_invalid",
                        "unsupported_goal",
                        "ambiguous_goal",
                    ]
                    .contains(&reason)
            }
            _ => false,
        })
    }
}

pub fn control_bridge(kind: &str, wire: &str) -> Result<Value, ()> {
    if kind == "interactive_goal_recovery" {
        let parsed: Envelope<InteractiveGoalRecovery> =
            serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&parsed, kind) || !parsed.result.valid()? {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "interactive_goal_review" {
        let parsed: Envelope<InteractiveGoalReview> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&parsed, kind) || !parsed.result.valid() {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "interactive_goal" {
        let parsed: Envelope<InteractiveGoal> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&parsed, kind) || !parsed.result.valid()? {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "goal_progress" {
        let parsed: Envelope<GoalProgress> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&parsed, kind) || !parsed.result.valid()? {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "record" {
        let parsed: Envelope<RecordEnvelope> = serde_json::from_str(wire).map_err(|_| ())?;
        let submission = optional_string(&parsed.result.submission_id)?;
        if !envelope(&parsed, "record")
            || !identifier(&parsed.result.service_instance_id, 128)
            || !parsed.result.identity.valid()
            || submission
                .as_ref()
                .is_some_and(|value| !identifier(value, 128))
            || !parsed.result.state.valid()
        {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "interrupt" {
        let parsed: Envelope<InterruptResult> = serde_json::from_str(wire).map_err(|_| ())?;
        let record = &parsed.result.record;
        let submission = optional_string(&record.submission_id)?;
        if !envelope(&parsed, "interrupt")
            || !identifier(&record.service_instance_id, 128)
            || !record.identity.valid()
            || submission
                .as_ref()
                .is_some_and(|item| !identifier(item, 128))
            || !record.state.valid()
            || !["requested", "already_terminal"].contains(&parsed.result.disposition.as_str())
            || (parsed.result.disposition == "requested" && !record.state.interrupt_requested)
            || (parsed.result.disposition == "already_terminal" && !terminal(&record.state.status))
        {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "not_found" {
        let parsed: Envelope<Box<RawValue>> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&parsed, "not_found") || parsed.result.get() != "null" {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    if kind == "failure" || kind == "app_failure" {
        let parsed: Envelope<Failure> = serde_json::from_str(wire).map_err(|_| ())?;
        let allowed = if kind == "failure" {
            [
                "service_instance_changed",
                "submission_conflict",
                "submission_ledger_full",
                "execution_busy",
                "execution_not_retained",
                "execution_unsupported",
            ]
            .contains(&parsed.result.code.as_str())
        } else {
            APP_ERROR_CODES.contains(&parsed.result.code.as_str())
        };
        if !envelope(&parsed, kind) || !allowed {
            return Err(());
        }
        return serde_json::to_value(parsed).map_err(|_| ());
    }
    Err(())
}

#[allow(dead_code)] // Used by the attachment binary, not the value-only binary.
pub fn source_value(wire: &str) -> Result<Value, ()> {
    let source: Source = serde_json::from_str(wire).map_err(|_| ())?;
    if !source.identity.valid()
        || source
            .user_choice
            .as_ref()
            .is_some_and(|choice| !choice.valid())
        || source.title.trim().is_empty()
        || source.title.chars().count() > 256
        || source.records.len() > 4096
        || source.records.iter().any(|record| {
            !["user", "assistant", "status", "error"].contains(&record.kind.as_str())
                || record.text.chars().count() > 262_144
        })
    {
        return Err(());
    }
    serde_json::to_value(source).map_err(|_| ())
}
#[allow(dead_code)] // Used by the attachment binary, not the value-only binary.
pub fn identity_value(wire: &str) -> Result<Value, ()> {
    let identity: Identity = serde_json::from_str(wire).map_err(|_| ())?;
    if !identity.valid() {
        return Err(());
    }
    serde_json::to_value(identity).map_err(|_| ())
}

#[cfg(test)]
mod submission_mode_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn attachment_snapshot_accepts_only_canonical_optional_mode() {
        let mut source = json!({
            "identity": {"productId":"coding", "continuityId":"continuity", "sessionId":"session", "scope":"cwd", "scopeFingerprint":"a".repeat(64)},
            "title":"Recovered", "cursor":2, "revision":1, "running":false,
            "records":[{"kind":"user", "text":"preserved history"}]
        });
        let legacy = source_value(&source.to_string()).unwrap();
        assert!(legacy.get("submissionMode").is_none());
        source["submissionMode"] = json!("execution");
        let restored = source_value(&source.to_string()).unwrap();
        assert_eq!(restored["submissionMode"], "execution");
        assert_eq!(restored["records"], source["records"]);
        for invalid in [
            json!(null),
            json!("legacy"),
            json!("unknown"),
            json!(1),
            json!({}),
        ] {
            source["submissionMode"] = invalid;
            assert!(source_value(&source.to_string()).is_err());
        }
        source["submissionMode"] = json!("execution");
        source["unexpected"] = json!(true);
        assert!(source_value(&source.to_string()).is_err());
    }
}

#[cfg(test)]
mod user_choice_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn attachment_preserves_a_valid_choice_and_rejects_duplicate_ids() {
        let mut source = json!({
            "identity": {"productId":"coding", "continuityId":"continuity", "sessionId":"session", "scope":"cwd", "scopeFingerprint":"a".repeat(64)},
            "title":"Plans", "cursor":2, "revision":2, "running":false, "records":[],
            "userChoice": {"questionId":"question", "question":"Which plan?", "options":[
                {"id":"a", "label":"Small steps", "description":null},
                {"id":"b", "label":"Rewrite", "description":"In one phase"}
            ]}
        });
        let projected = source_value(&source.to_string()).unwrap();
        assert_eq!(projected["userChoice"], source["userChoice"]);
        source["userChoice"]["options"][1]["id"] = json!("a");
        assert!(source_value(&source.to_string()).is_err());
    }
}
