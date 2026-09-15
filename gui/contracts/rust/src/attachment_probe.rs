//! Sequential read-only attachment experiment, not an ongoing RPC dispatcher.
use super::transport_auth::Channel;
use serde::{Deserialize, Serialize};
use serde_json::{json, value::RawValue, Value};
use std::collections::BTreeSet;
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
    fn validate(&self) -> Result<(), ()> {
        let mux = &self.mux_space;
        if !identifier(&self.attachment_id, 512)
            || !positive(&self.controller_generation)
            || !identifier(&mux.mux_space_id, 512)
            || mux.name != "gui-fixture"
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
fn membership_barrier<R: Read, W: Write>(
    channel: &mut Channel<R, W>,
    expected: &Mux,
    next_id: &mut usize,
    attempt: &super::connection_epoch::Attempt,
) -> Result<(), ()> {
    let id = next_id.to_string();
    *next_id += 1;
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

pub fn run<R: Read, W: Write>(
    channel: &mut Channel<R, W>,
    instance: &str,
    attempt: &super::connection_epoch::Attempt,
) -> Result<usize, ()> {
    let response = request(
        channel,
        "mux/attach",
        "1",
        json!({"selector":{"muxSpaceId":null,"name":"gui-fixture"},"mailboxCapacity":256}),
    )?;
    // Any attach error/conflict closes this attempt; never take over or retry.
    if response.result_type != "attachment" {
        return Err(());
    }
    let attachment: Attachment = serde_json::from_str(response.result.get()).map_err(|_| ())?;
    attempt.apply(|| attachment.validate())?;
    let mut next_id = 2usize;
    let snapshots = (|| {
        let mut pending = Vec::new();
        for session in &attachment.sessions {
            let id = next_id.to_string();
            next_id += 1;
            let payload = Request {
                protocol_version: "loushang.execution/v1",
                request_id: &id,
                operation: "execution/snapshot",
                payload: SnapshotRequest {
                    control: Control {
                        attachment_id: &attachment.attachment_id,
                        controller_generation: &attachment.controller_generation,
                        member_id: &session.member.member_id,
                    },
                    expected_instance_id: instance,
                },
            };
            channel.send(&serde_json::to_vec(&payload).map_err(|_| ())?)?;
            let bytes = channel.receive()?;
            let snapshot =
                projection::bridge("snapshot", std::str::from_utf8(&bytes).map_err(|_| ())?)?;
            let source = &snapshot["result"]["source"]["source"];
            let before = projection::source_value(session.snapshot.get())?;
            let old = before["cursor"].as_str().ok_or(())?;
            let new = source["cursor"].as_str().ok_or(())?;
            if snapshot["requestId"] != id
                || snapshot["result"]["serviceInstanceId"] != instance
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
        membership_barrier(channel, &attachment.mux_space, &mut next_id, attempt)?;
        // Exercise multiple batches without resetting watermarks to the snapshot.
        // Lifetime is still bounded by the connection deadline, not a GUI owner.
        let mut readers = pending
            .iter()
            .map(EventReader::new)
            .collect::<Result<Vec<_>, _>>()?;
        for _round in 0..2 {
            for (session, reader) in attachment.sessions.iter().zip(&mut readers) {
                let id = next_id.to_string();
                next_id += 1;
                channel.send(
                    &serde_json::to_vec(&Request {
                        protocol_version: "loushang.execution/v1",
                        request_id: &id,
                        operation: "execution/read_events",
                        payload: SnapshotRequest {
                            control: Control {
                                attachment_id: &attachment.attachment_id,
                                controller_generation: &attachment.controller_generation,
                                member_id: &session.member.member_id,
                            },
                            expected_instance_id: instance,
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
            }
            membership_barrier(channel, &attachment.mux_space, &mut next_id, attempt)?;
        }
        Ok(pending.len())
    })();
    if snapshots.is_err() {
        attempt.cancellation().invalidate();
    }
    // Once ownership is validated, attempt detach even if a snapshot/batch is rejected.
    let detached = request(
        channel,
        "mux/detach",
        &next_id.to_string(),
        Detach {
            attachment_id: &attachment.attachment_id,
            controller_generation: &attachment.controller_generation,
        },
    );
    let count = snapshots?;
    let detached = detached?;
    if detached.result_type != "ack" || serde_json::from_str::<Ack>(detached.result.get()).is_err()
    {
        return Err(());
    }
    Ok(count)
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
