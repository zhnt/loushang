//! Partial idle snapshot and content-event adapter; metadata updates are not supported.
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
struct Idle {
    execution_id: Box<RawValue>,
    status: Box<RawValue>,
    final_cursor: Box<RawValue>,
}
impl Idle {
    fn valid(&self) -> bool {
        self.execution_id.get() == "null"
            && self.status.get() == "null"
            && self.final_cursor.get() == "null"
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SourceSnapshot {
    source: Source,
    observation: Idle,
    draft: String,
    truncated: bool,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct View {
    identity: Identity,
    revision: u64,
    quiescent: Idle,
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
    events: Vec<Content>,
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
            || !e.result.source.draft.is_empty()
            || view.revision > 9_007_199_254_740_991
            || !view.quiescent.valid()
            || view.active.get() != "null"
            || view.latest_terminal.get() != "null"
        {
            return Err(());
        }
        serde_json::to_value(e).map_err(|_| ())
    } else {
        let e: Envelope<Events> = serde_json::from_str(wire).map_err(|_| ())?;
        if !envelope(&e, "events") || e.result.events.len() > 256 {
            return Err(());
        }
        for content in &e.result.events {
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
        }
        serde_json::to_value(e).map_err(|_| ())
    }
}
