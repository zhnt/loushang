//! Sequential read-only attachment and membership-barrier implementation.
use super::transport_auth::Channel;
use serde::{Deserialize, Serialize};
use serde_json::{json, value::RawValue, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{Read, Write};
#[path = "projection.rs"]
mod projection;
fn identifier(value: &str, max: usize) -> bool {
    !value.is_empty()
        && value.len() <= max
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._~-".contains(&byte))
}
fn positive(raw: &RawValue) -> bool {
    let value = raw.get();
    !value.is_empty() && !value.starts_with('0') && value.bytes().all(|byte| byte.is_ascii_digit())
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Envelope {
    protocol_version: String,
    request_id: String,
    result_type: String,
    result: Box<RawValue>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Ack {}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Member {
    member_id: String,
    session: Box<RawValue>,
    title: String,
    position: u16,
}
impl Member {
    fn value(&self) -> Result<Value, ()> {
        if !identifier(&self.member_id, 512)
            || self.title.trim().is_empty()
            || self.title.chars().count() > 256
            || self.position == 0
        {
            return Err(());
        }
        Ok(
            json!({"memberId": self.member_id, "session": projection::identity_value(self.session.get())?, "title": self.title, "position": self.position}),
        )
    }
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Mux {
    mux_space_id: String,
    name: String,
    revision: Box<RawValue>,
    members: Vec<Member>,
}
impl Mux {
    fn matches(&self, current: &Self) -> Result<(), ()> {
        if self.mux_space_id != current.mux_space_id
            || self.name != current.name
            || self.revision.get() != current.revision.get()
            || self.members.len() != current.members.len()
        {
            return Err(());
        }
        for (before, after) in self.members.iter().zip(&current.members) {
            if before.value()? != after.value()? {
                return Err(());
            }
        }
        Ok(())
    }

    fn bridge_value(&self) -> Result<Value, ()> {
        Ok(json!({
            "muxSpaceId": self.mux_space_id,
            "name": self.name,
            "revision": self.revision.get(),
            "members": self.members.iter().map(|member| Ok(json!({
                "memberId": member.member_id,
                "session": projection::identity_value(member.session.get())?,
                "title": member.title,
                "position": member.position.to_string(),
            }))).collect::<Result<Vec<_>, ()>>()?,
        }))
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Session {
    member: Member,
    snapshot: Box<RawValue>,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Attachment {
    attachment_id: String,
    controller_generation: Box<RawValue>,
    mux_space: Mux,
    sessions: Vec<Session>,
}
impl Attachment {
    fn validate(&self, expected_name: &str) -> Result<(), ()> {
        let mux = &self.mux_space;
        if !identifier(&self.attachment_id, 512)
            || !positive(&self.controller_generation)
            || !identifier(&mux.mux_space_id, 512)
            || mux.name != expected_name
            || !positive(&mux.revision)
            || mux.members.len() > 128
            || mux.members.len() != self.sessions.len()
        {
            return Err(());
        }
        let mut members = BTreeSet::new();
        let mut sessions = BTreeSet::new();
        for (index, (member, attached)) in mux.members.iter().zip(&self.sessions).enumerate() {
            let value = member.value()?;
            let source = projection::source_value(attached.snapshot.get())?;
            if member.position as usize != index + 1
                || value != attached.member.value()?
                || value["session"] != source["identity"]
                || !members.insert(member.member_id.clone())
                || !sessions.insert(value["session"]["sessionId"].as_str().ok_or(())?.to_owned())
            {
                return Err(());
            }
        }
        Ok(())
    }
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Request<'a, P> {
    protocol_version: &'a str,
    request_id: &'a str,
    operation: &'a str,
    payload: P,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Detach<'a> {
    attachment_id: &'a str,
    controller_generation: &'a RawValue,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Control<'a> {
    attachment_id: &'a str,
    controller_generation: &'a RawValue,
    member_id: &'a str,
}
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SnapshotRequest<'a> {
    control: Control<'a>,
    expected_instance_id: &'a str,
}
fn request<R: Read, W: Write, P: Serialize>(
    channel: &mut Channel<R, W>,
    operation: &str,
    id: &str,
    payload: P,
) -> Result<Envelope, ()> {
    channel.send(
        &serde_json::to_vec(&Request {
            protocol_version: "loushang.app/v1",
            request_id: id,
            operation,
            payload,
        })
        .map_err(|_| ())?,
    )?;
    let envelope: Envelope = serde_json::from_slice(&channel.receive()?).map_err(|_| ())?;
    if envelope.protocol_version != "loushang.app/v1" || envelope.request_id != id {
        return Err(());
    }
    Ok(envelope)
}
fn take_request_id(next: &mut u64) -> Result<String, ()> {
    if *next == 0 || *next > i64::MAX as u64 {
        return Err(());
    }
    let id = next.to_string();
    *next += 1;
    Ok(id)
}

fn membership_barrier<R: Read, W: Write>(
    channel: &mut Channel<R, W>,
    expected: &Mux,
    next_id: &mut u64,
    attempt: &super::connection_epoch::Attempt,
) -> Result<(), ()> {
    let id = take_request_id(next_id)?;
    let response = request(
        channel,
        "mux/read",
        &id,
        json!({"selector":{"muxSpaceId":expected.mux_space_id,"name":null}}),
    )?;
    if response.result_type != "mux" {
        return Err(());
    }
    let current: Mux = serde_json::from_str(response.result.get()).map_err(|_| ())?;
    attempt.apply(|| expected.matches(&current))
}

/// Owns validated attachment authority and per-member read state, not the socket.
/// The caller must attempt detach before discarding an attached session.
pub(crate) struct ReadSession {
    attachment: Attachment,
    instance: String,
    next_id: u64,
    readers: Option<Vec<EventReader>>,
    closed: bool,
}

#[derive(Clone)]
pub(crate) struct ControlAuthority {
    attachment_id: String,
    controller_generation: String,
    instance: String,
    members: BTreeMap<String, String>,
}

pub(crate) enum ControlResult {
    Accepted,
    Missing,
    Rejected(String),
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct InitialSnapshot {
    pub(crate) mux_space: Value,
    pub(crate) sessions: Vec<Value>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MemberEvents {
    pub(crate) member_id: String,
    pub(crate) session_id: String,
    pub(crate) events: Vec<Value>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PollRound {
    pub(crate) members: Vec<MemberEvents>,
    pub(crate) sessions: Vec<Value>,
}

impl ReadSession {
    pub(crate) fn attach<R: Read, W: Write>(
        channel: &mut Channel<R, W>,
        instance: &str,
        mux_name: &str,
        attempt: &super::connection_epoch::Attempt,
    ) -> Result<Self, ()> {
        let response = request(
            channel,
            "mux/attach",
            "1",
            json!({"selector":{"muxSpaceId":null,"name":mux_name},"mailboxCapacity":256}),
        )?;
        if response.result_type != "attachment" {
            return Err(());
        }
        let attachment: Attachment = serde_json::from_str(response.result.get()).map_err(|_| ())?;
        attempt.apply(|| attachment.validate(mux_name))?;
        Ok(Self {
            attachment,
            instance: instance.to_owned(),
            next_id: 2,
            readers: None,
            closed: false,
        })
    }

    pub(crate) fn initialize<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        attempt: &super::connection_epoch::Attempt,
    ) -> Result<InitialSnapshot, ()> {
        if self.closed || self.readers.is_some() {
            return Err(());
        }
        let result = (|| {
            attempt.apply(|| Ok(()))?;
            let pending = self.read_snapshots(channel, attempt)?;
            membership_barrier(
                channel,
                &self.attachment.mux_space,
                &mut self.next_id,
                attempt,
            )?;
            let readers = pending
                .iter()
                .map(EventReader::new)
                .collect::<Result<Vec<_>, _>>()?;
            let initial = InitialSnapshot {
                mux_space: self.attachment.mux_space.bridge_value()?,
                sessions: pending
                    .iter()
                    .map(|value| value["result"].clone())
                    .collect(),
            };
            attempt.apply(|| {
                self.readers = Some(readers);
                Ok(initial)
            })
        })();
        if result.is_err() {
            self.fail(attempt);
        }
        result
    }

    pub(crate) fn control_authority(&self) -> Result<ControlAuthority, ()> {
        if self.closed {
            return Err(());
        }
        let mut members = BTreeMap::new();
        for session in &self.attachment.sessions {
            let identity = projection::identity_value(session.member.session.get())?;
            let session_id = identity["sessionId"].as_str().ok_or(())?.to_owned();
            if members
                .insert(session_id, session.member.member_id.clone())
                .is_some()
            {
                return Err(());
            }
        }
        Ok(ControlAuthority {
            attachment_id: self.attachment.attachment_id.clone(),
            controller_generation: self.attachment.controller_generation.get().to_owned(),
            instance: self.instance.clone(),
            members,
        })
    }

    pub(crate) fn next_control_request_id(&mut self) -> Result<String, ()> {
        if self.closed {
            return Err(());
        }
        take_request_id(&mut self.next_id)
    }

    /// One complete round, with no hard-coded lifetime or round count.
    /// No partial per-member cursor changes survive a failed round.
    pub(crate) fn poll<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        attempt: &super::connection_epoch::Attempt,
        stop: Option<&crate::read_stop::ReadStop>,
    ) -> Result<Option<PollRound>, ()> {
        if self.closed {
            return Err(());
        }
        let result = (|| {
            attempt.apply(|| Ok(()))?;
            let mut next = self.readers.as_ref().ok_or(())?.clone();
            let mut members = Vec::with_capacity(next.len());
            for (session, reader) in self.attachment.sessions.iter().zip(&mut next) {
                if stop.map(|s| s.requested()).transpose()?.unwrap_or(false) {
                    return Ok(None);
                }
                let id = take_request_id(&mut self.next_id)?;
                channel.send(
                    &serde_json::to_vec(&Request {
                        protocol_version: "loushang.execution/v1",
                        request_id: &id,
                        operation: "execution/read_events",
                        payload: SnapshotRequest {
                            control: Control {
                                attachment_id: &self.attachment.attachment_id,
                                controller_generation: &self.attachment.controller_generation,
                                member_id: &session.member.member_id,
                            },
                            expected_instance_id: &self.instance,
                        },
                    })
                    .map_err(|_| ())?,
                )?;
                let bytes = channel.receive()?;
                let events =
                    projection::bridge("events", std::str::from_utf8(&bytes).map_err(|_| ())?)?;
                if events["requestId"] != id {
                    return Err(());
                }
                attempt.apply(|| reader.apply(&events))?;
                members.push(MemberEvents {
                    member_id: session.member.member_id.clone(),
                    session_id: reader.session_id.as_str().ok_or(())?.to_owned(),
                    events: events["result"]["events"].as_array().ok_or(())?.clone(),
                });
            }
            if stop.map(|s| s.requested()).transpose()?.unwrap_or(false) {
                return Ok(None);
            }
            let has_events = members.iter().any(|member| !member.events.is_empty());
            let sessions = if has_events {
                self.read_snapshots(channel, attempt)?
                    .iter()
                    .map(|value| value["result"].clone())
                    .collect()
            } else {
                Vec::new()
            };
            membership_barrier(
                channel,
                &self.attachment.mux_space,
                &mut self.next_id,
                attempt,
            )?;
            attempt.apply(|| {
                self.readers = Some(next);
                Ok(has_events.then_some(PollRound { members, sessions }))
            })
        })();
        if result.is_err() {
            self.fail(attempt);
        }
        result
    }

    fn read_snapshots<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        attempt: &super::connection_epoch::Attempt,
    ) -> Result<Vec<Value>, ()> {
        let mut pending = Vec::with_capacity(self.attachment.sessions.len());
        for session in &self.attachment.sessions {
            let id = take_request_id(&mut self.next_id)?;
            channel.send(
                &serde_json::to_vec(&Request {
                    protocol_version: "loushang.execution/v1",
                    request_id: &id,
                    operation: "execution/snapshot",
                    payload: SnapshotRequest {
                        control: Control {
                            attachment_id: &self.attachment.attachment_id,
                            controller_generation: &self.attachment.controller_generation,
                            member_id: &session.member.member_id,
                        },
                        expected_instance_id: &self.instance,
                    },
                })
                .map_err(|_| ())?,
            )?;
            let bytes = channel.receive()?;
            let snapshot =
                projection::bridge("snapshot", std::str::from_utf8(&bytes).map_err(|_| ())?)?;
            let source = &snapshot["result"]["source"]["source"];
            let before = projection::source_value(session.snapshot.get())?;
            let old = before["cursor"].as_str().ok_or(())?;
            let new = source["cursor"].as_str().ok_or(())?;
            if snapshot["requestId"] != id
                || snapshot["result"]["serviceInstanceId"] != self.instance
                || source["identity"] != before["identity"]
                || new.len() < old.len()
                || (new.len() == old.len() && new < old)
            {
                return Err(());
            }
            attempt.apply(|| {
                pending.push(snapshot);
                Ok(())
            })?;
        }
        Ok(pending)
    }

    fn fail(&mut self, attempt: &super::connection_epoch::Attempt) {
        self.readers = None;
        attempt.cancellation().invalidate();
    }

    pub(crate) fn detach<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        attempt: &super::connection_epoch::Attempt,
    ) -> Result<(), ()> {
        if self.closed {
            return Err(());
        }
        self.closed = true;
        self.readers = None;
        // Keep cleanup possible after local invalidation; use exact owned authority.
        let result = (|| {
            let id = take_request_id(&mut self.next_id)?;
            let response = request(
                channel,
                "mux/detach",
                &id,
                Detach {
                    attachment_id: &self.attachment.attachment_id,
                    controller_generation: &self.attachment.controller_generation,
                },
            )?;
            if response.result_type != "ack"
                || serde_json::from_str::<Ack>(response.result.get()).is_err()
            {
                return Err(());
            }
            Ok(())
        })();
        if result.is_err() {
            attempt.cancellation().invalidate();
        }
        result
    }
}

impl ControlAuthority {
    fn payload(&self, session_id: &str) -> Result<Value, ()> {
        let member_id = self.members.get(session_id).ok_or(())?;
        let generation: Value =
            serde_json::from_str(&self.controller_generation).map_err(|_| ())?;
        Ok(json!({
            "control": {
                "attachmentId": self.attachment_id,
                "controllerGeneration": generation,
                "memberId": member_id,
            },
            "expectedInstanceId": self.instance,
        }))
    }

    pub(crate) fn submit<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        submission_id: &str,
        text: &str,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        if !identifier(submission_id, 128)
            || text.trim().is_empty()
            || text.chars().count() > 262_144
        {
            return Err(());
        }
        let mut payload = self.payload(session_id)?;
        payload["submissionId"] = Value::String(submission_id.to_owned());
        payload["text"] = Value::String(text.to_owned());
        let result = execution_request(channel, "execution/submit", request_id, payload)?;
        self.record_result(result, session_id, Some(submission_id))
    }

    pub(crate) fn find_submission<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        submission_id: &str,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        if !identifier(submission_id, 128) {
            return Err(());
        }
        let mut payload = self.payload(session_id)?;
        payload["submissionId"] = Value::String(submission_id.to_owned());
        let result = execution_request(channel, "execution/find_submission", request_id, payload)?;
        if result["resultType"] == "not_found" {
            projection::control_bridge("not_found", &result.to_string())?;
            return Ok(ControlResult::Missing);
        }
        self.record_result(result, session_id, Some(submission_id))
    }

    pub(crate) fn interrupt<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        execution_id: &str,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        if !identifier(execution_id, 128) {
            return Err(());
        }
        let mut payload = self.payload(session_id)?;
        payload["executionId"] = Value::String(execution_id.to_owned());
        let result = execution_request(channel, "execution/interrupt", request_id, payload)?;
        if let Some(rejected) = rejected_result(&result)? {
            return Ok(ControlResult::Rejected(rejected));
        }
        let checked = projection::control_bridge("interrupt", &result.to_string())?;
        let record = &checked["result"]["record"];
        if record["serviceInstanceId"] != self.instance
            || record["identity"]["sessionId"] != session_id
            || record["state"]["executionId"] != execution_id
        {
            return Err(());
        }
        Ok(ControlResult::Accepted)
    }

    fn record_result(
        &self,
        result: Value,
        session_id: &str,
        submission_id: Option<&str>,
    ) -> Result<ControlResult, ()> {
        if let Some(rejected) = rejected_result(&result)? {
            return Ok(ControlResult::Rejected(rejected));
        }
        let checked = projection::control_bridge("record", &result.to_string())?;
        let record = &checked["result"];
        if record["serviceInstanceId"] != self.instance
            || record["identity"]["sessionId"] != session_id
            || submission_id.is_some_and(|value| record["submissionId"] != value)
        {
            return Err(());
        }
        Ok(ControlResult::Accepted)
    }
}

fn execution_request<R: Read, W: Write>(
    channel: &mut Channel<R, W>,
    operation: &str,
    id: &str,
    payload: Value,
) -> Result<Value, ()> {
    let request = serde_json::to_vec(&json!({
        "protocolVersion": "loushang.execution/v1",
        "requestId": id,
        "operation": operation,
        "payload": payload,
    }))
    .map_err(|_| ())?;
    channel.send(&request)?;
    let value: Value = serde_json::from_slice(&channel.receive()?).map_err(|_| ())?;
    if value["requestId"] != id {
        return Err(());
    }
    Ok(value)
}

fn rejected_result(value: &Value) -> Result<Option<String>, ()> {
    let kind = value["resultType"].as_str().ok_or(())?;
    if kind != "failure" && kind != "app_failure" {
        return Ok(None);
    }
    let checked = projection::control_bridge(kind, &value.to_string())?;
    Ok(Some(
        checked["result"]["code"].as_str().ok_or(())?.to_owned(),
    ))
}

fn successor(decimal: &str) -> String {
    let mut bytes = decimal.as_bytes().to_vec();
    for digit in bytes.iter_mut().rev() {
        if *digit < b'9' {
            *digit += 1;
            return String::from_utf8(bytes).expect("decimal input");
        }
        *digit = b'0';
    }
    bytes.insert(0, b'1');
    String::from_utf8(bytes).expect("decimal input")
}

// Inputs have passed the independent wire validators. Keep content and metadata
// watermarks separate, and never coerce arbitrary-size source cursors to floats.
#[derive(Clone)]
struct EventReader {
    session_id: Value,
    cursor: String,
    revision: u64,
    valid: bool,
}
impl EventReader {
    fn new(snapshot: &Value) -> Result<Self, ()> {
        let source = &snapshot["result"]["source"]["source"];
        Ok(Self {
            session_id: source["identity"]["sessionId"].clone(),
            cursor: source["cursor"].as_str().ok_or(())?.to_owned(),
            revision: snapshot["result"]["executions"]["revision"]
                .as_u64()
                .ok_or(())?,
            valid: true,
        })
    }
    fn apply(&mut self, events: &Value) -> Result<(), ()> {
        if !self.valid {
            return Err(());
        }
        let mut next = self.clone();
        if next.advance(events).is_err() {
            self.valid = false;
            return Err(());
        }
        *self = next;
        Ok(())
    }
    fn advance(&mut self, events: &Value) -> Result<(), ()> {
        for event in events["result"]["events"].as_array().ok_or(())? {
            if event.get("source").is_some() {
                let content = &event["source"];
                if content["sessionId"] != self.session_id
                    || content["cursor"].as_str() != Some(successor(&self.cursor).as_str())
                {
                    return Err(());
                }
                self.cursor = content["cursor"].as_str().ok_or(())?.to_owned();
            } else {
                let next = event["revision"].as_u64().ok_or(())?;
                if self.revision.checked_add(1) != Some(next) {
                    return Err(());
                }
                self.revision = next;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn request_numbers_fail_closed_without_wrapping() {
        let mut next = i64::MAX as u64;
        assert_eq!(take_request_id(&mut next).unwrap(), i64::MAX.to_string());
        assert!(take_request_id(&mut next).is_err());
        assert!(take_request_id(&mut 0).is_err());
    }
    fn validate_events(snapshot: &Value, events: &Value) -> Result<(), ()> {
        EventReader::new(snapshot)?.apply(events)
    }
    #[test]
    fn batches_are_atomic_and_failures_fence_the_reader() {
        let snapshot = json!({"result":{"source":{"source":{"cursor":"9", "identity":{"sessionId":"s"}}},"executions":{"revision":7}}});
        let batch = |cursors: &[&str]| json!({"result":{"events":cursors.iter().map(|c| json!({"source":{"sessionId":"s","cursor":c}})).collect::<Vec<_>>()}});
        let mut reader = EventReader::new(&snapshot).unwrap();
        reader.apply(&batch(&["10"])).unwrap();
        reader.apply(&batch(&["11"])).unwrap();
        assert_eq!(reader.cursor, "11");
        assert!(reader.apply(&batch(&["12", "14"])).is_err());
        assert_eq!(reader.cursor, "11"); // No partial advancement.
        assert!(reader.apply(&batch(&["12"])).is_err());
        assert!(reader.apply(&batch(&[])).is_err());
        let mut fresh = EventReader::new(&snapshot).unwrap();
        assert!(fresh.apply(&batch(&["11"])).is_err()); // Cannot reuse a later batch.
    }
    #[test]
    fn decimal_successor_is_lossless() {
        assert_eq!(successor("0"), "1");
        assert_eq!(
            successor("99999999999999999999999999999"),
            "100000000000000000000000000000"
        );
    }
    #[test]
    fn content_and_metadata_have_separate_contiguous_watermarks() {
        let snapshot = json!({"result":{"source":{"source":{"cursor":"999999999999999999999", "identity":{"sessionId":"s"}}},"executions":{"revision":7}}});
        let content = json!({"source":{"sessionId":"s","cursor":"1000000000000000000000"}});
        let batch = |items: Vec<Value>| json!({"result":{"events":items}});
        assert!(validate_events(
            &snapshot,
            &batch(vec![content.clone(), json!({"revision":8})])
        )
        .is_ok());
        assert!(validate_events(&snapshot, &batch(vec![content.clone(), content])).is_err());
        assert!(validate_events(&snapshot, &batch(vec![json!({"revision":9})])).is_err());
        assert!(validate_events(
            &snapshot,
            &batch(vec![
                json!({"source":{"sessionId":"other","cursor":"1000000000000000000000"}})
            ])
        )
        .is_err());
    }
}
