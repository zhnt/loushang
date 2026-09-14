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
pub fn run<R: Read, W: Write>(channel: &mut Channel<R, W>, instance: &str) -> Result<usize, ()> {
    let response = request(
        channel,
        "mux/attach",
        "attach",
        json!({"selector":{"muxSpaceId":null,"name":"gui-fixture"},"mailboxCapacity":256}),
    )?;
    // Any attach error/conflict closes this attempt; never take over or retry.
    if response.result_type != "attachment" {
        return Err(());
    }
    let attachment: Attachment = serde_json::from_str(response.result.get()).map_err(|_| ())?;
    attachment.validate()?;
    let snapshots = (|| {
        let mut pending = Vec::new();
        for (index, session) in attachment.sessions.iter().enumerate() {
            let id = format!("snapshot-{index}");
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
            pending.push(snapshot);
        }
        Ok(pending.len())
    })();
    // Once ownership is validated, attempt detach even if a snapshot is rejected.
    let detached = request(
        channel,
        "mux/detach",
        "detach",
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
