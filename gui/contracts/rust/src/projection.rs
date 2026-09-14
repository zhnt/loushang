//! Offline snapshot and content/metadata-event contract projection, not a live client.
use super::identifier;
use serde::{Deserialize, Serialize};
use serde_json::{value::RawValue, Value};

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
    identity: Identity,
    title: String,
    cursor: Counter,
    revision: Counter,
    running: bool,
    records: Vec<Record>,
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
        serde_json::from_str::<LegacyFailure>(outcome.legacy_result.get()).is_ok_and(|v| {
            [
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
                "cleanup_incomplete",
                "service_closed",
            ]
            .contains(&v.code.as_str())
        })
    }
}
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
            || !identifier(&e.result.service_instance_id, 128)
            || !s.identity.valid()
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
