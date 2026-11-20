//! Sequential read-only attachment and membership-barrier implementation.
use super::{
    transport_auth::Channel, InteractiveGoalCommand, InteractiveGoalReviewDecision,
    InteractiveGoalReviewSubmission,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, value::RawValue, Value};
use sha2::{Digest, Sha256};
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
pub(super) struct Envelope {
    protocol_version: String,
    request_id: String,
    pub(super) result_type: String,
    pub(super) result: Box<RawValue>,
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
struct ReadAttachmentEvents<'a> {
    attachment_id: &'a str,
    controller_generation: &'a RawValue,
    limit: u8,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RespondInteraction<'a> {
    attachment_id: &'a str,
    controller_generation: &'a RawValue,
    member_id: &'a str,
    interaction_id: &'a str,
    outcome: InteractionOutcome,
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
pub(super) fn request<R: Read, W: Write, P: Serialize>(
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
    default_template: Option<SessionTemplate>,
}

#[derive(Clone)]
pub struct ControlAuthority {
    attachment_id: String,
    controller_generation: String,
    instance: String,
    mux_name: String,
    mux_space_id: String,
    members: BTreeMap<String, String>,
    session_templates: BTreeMap<String, SessionTemplate>,
    default_template: Option<SessionTemplate>,
}

#[derive(Clone)]
struct SessionTemplate {
    product_id: String,
    scope: String,
    scope_fingerprint: String,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InteractionOutcome {
    Approve,
    Deny,
    Cancel,
}

pub enum ControlResult {
    Accepted,
    Submitted(String),
    Missing,
    Rejected(String),
}

pub enum ModelControlResult {
    Accepted(Value),
    Rejected(String),
}

pub enum CreateSessionResult {
    Accepted(String),
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
pub struct MemberEvents {
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
        record: &super::transport_auth::record_value::Record,
        workspace_scope: Option<&super::WorkspaceInfo>,
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
            default_template: workspace_scope
                .map(|workspace| {
                    let scope = match workspace.scope {
                        super::WorkspaceScope::Cwd => "cwd",
                        super::WorkspaceScope::UserHome => "user_home",
                    };
                    (
                        record.product_id(),
                        scope,
                        workspace.scope_fingerprint.as_str(),
                    )
                })
                .or_else(|| record.creation_context())
                .map(|(product, scope, fingerprint)| SessionTemplate {
                    product_id: product.to_owned(),
                    scope: scope.to_owned(),
                    scope_fingerprint: fingerprint.to_owned(),
                }),
        })
    }

    /// Prepare an empty controlled mux before publishing its first snapshot.
    /// A stable continuity identity lets AppHost recover the same Session after
    /// a lost reply/restart; existing members always win over default creation.
    pub(crate) fn ensure_default<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        attempt: &super::connection_epoch::Attempt,
    ) -> Result<(), ()> {
        if !self.attachment.sessions.is_empty() {
            return Ok(());
        }
        let continuity_id = format!(
            "gui-default-{:x}",
            Sha256::digest(self.attachment.mux_space.mux_space_id.as_bytes())
        );
        let authority = self.control_authority()?;
        let request_id = self.next_control_request_id()?;
        match authority.create_session(channel, None, &continuity_id, "New Session", &request_id)? {
            CreateSessionResult::Accepted(_) => (),
            CreateSessionResult::Rejected(_) => return Err(()),
        }
        // Member publication invalidates the old controller. Acquire its new
        // authoritative attachment before exposing any Session to the WebView.
        let request_id = self.next_control_request_id()?;
        let response = request(
            channel,
            "mux/attach",
            &request_id,
            json!({"selector":{"muxSpaceId":null,"name":self.attachment.mux_space.name},"mailboxCapacity":256}),
        )?;
        if response.result_type != "attachment" {
            return Err(());
        }
        let attachment: Attachment = serde_json::from_str(response.result.get()).map_err(|_| ())?;
        attempt.apply(|| attachment.validate(&self.attachment.mux_space.name))?;
        self.attachment = attachment;
        Ok(())
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
            let mut readers = pending
                .iter()
                .map(EventReader::new)
                .collect::<Result<Vec<_>, _>>()?;
            let attached_cursors = self
                .attachment
                .sessions
                .iter()
                .map(|session| {
                    let source = projection::source_value(session.snapshot.get())?;
                    source["cursor"].as_str().map(str::to_owned).ok_or(())
                })
                .collect::<Result<Vec<_>, _>>()?;
            self.fill_approval_gaps(channel, &mut readers, &attached_cursors)?;
            membership_barrier(
                channel,
                &self.attachment.mux_space,
                &mut self.next_id,
                attempt,
            )?;
            let initial = InitialSnapshot {
                mux_space: self.attachment.mux_space.bridge_value()?,
                sessions: approval_snapshots(pending, &readers),
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
        let mut session_templates = BTreeMap::new();
        for session in &self.attachment.sessions {
            let identity = projection::identity_value(session.member.session.get())?;
            let session_id = identity["sessionId"].as_str().ok_or(())?.to_owned();
            if members
                .insert(session_id.clone(), session.member.member_id.clone())
                .is_some()
            {
                return Err(());
            }
            if session_templates
                .insert(
                    session_id,
                    SessionTemplate {
                        product_id: identity["productId"].as_str().ok_or(())?.to_owned(),
                        scope: identity["scope"].as_str().ok_or(())?.to_owned(),
                        scope_fingerprint: identity["scopeFingerprint"]
                            .as_str()
                            .ok_or(())?
                            .to_owned(),
                    },
                )
                .is_some()
            {
                return Err(());
            }
        }
        Ok(ControlAuthority {
            attachment_id: self.attachment.attachment_id.clone(),
            controller_generation: self.attachment.controller_generation.get().to_owned(),
            instance: self.instance.clone(),
            mux_name: self.attachment.mux_space.name.clone(),
            mux_space_id: self.attachment.mux_space.mux_space_id.clone(),
            members,
            session_templates,
            default_template: self.default_template.clone(),
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
                let snapshots = self.read_snapshots(channel, attempt)?;
                if snapshots.len() != next.len() {
                    return Err(());
                }
                let cursors = next
                    .iter()
                    .map(|reader| reader.cursor.clone())
                    .collect::<Vec<_>>();
                for (reader, snapshot) in next.iter_mut().zip(&snapshots) {
                    reader.rebase(snapshot)?;
                }
                self.fill_approval_gaps(channel, &mut next, &cursors)?;
                approval_snapshots(snapshots, &next)
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

    // A new execution snapshot rebases the event stream. Read its covered
    // interactions from the existing attachment before the next execution poll.
    fn fill_approval_gaps<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
        readers: &mut [EventReader],
        previous: &[String],
    ) -> Result<(), ()> {
        if readers
            .iter()
            .zip(previous)
            .all(|(reader, cursor)| reader.cursor == *cursor)
        {
            return Ok(());
        }
        for _ in 0..=256 {
            let Some(entry) = self.read_attachment_event(channel)? else {
                return Ok(());
            };
            let index = self
                .attachment
                .sessions
                .iter()
                .position(|item| item.member.member_id == entry.member_id)
                .ok_or(())?;
            readers[index].apply_covered_interaction(entry.event, &previous[index])?;
        }
        Err(())
    }

    fn read_attachment_event<R: Read, W: Write>(
        &mut self,
        channel: &mut Channel<R, W>,
    ) -> Result<Option<AttachmentEvent>, ()> {
        let id = take_request_id(&mut self.next_id)?;
        let reply = request(
            channel,
            "attachment/read_events",
            &id,
            ReadAttachmentEvents {
                attachment_id: &self.attachment.attachment_id,
                controller_generation: &self.attachment.controller_generation,
                limit: 1,
            },
        )?;
        if reply.result_type != "events" {
            return Err(());
        }
        let batch: AttachmentEvents = serde_json::from_str(reply.result.get()).map_err(|_| ())?;
        match batch.events.as_slice() {
            [] => Ok(None),
            [entry]
                if entry.attachment_id == self.attachment.attachment_id
                    && entry.protocol_version == "loushang.app/v1" =>
            {
                Ok(batch.events.into_iter().next())
            }
            _ => Err(()),
        }
    }

    pub(crate) fn has_approval(&self, session_id: &str, interaction_id: &str) -> bool {
        self.readers.as_ref().is_some_and(|readers| {
            readers.iter().any(|reader| {
                reader.session_id == session_id && reader.approvals.contains_key(interaction_id)
            })
        })
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
    pub(crate) fn close_session<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        mux_space_id: &str,
        session_id: &str,
        request_id: &str,
    ) -> Result<bool, ()> {
        if mux_space_id != self.mux_space_id {
            return Ok(false);
        }
        let Some(member_id) = self.members.get(session_id) else {
            return Ok(false);
        };
        let response = request(
            channel,
            "mux/member/close",
            request_id,
            json!({
                "selector": {"muxSpaceId": self.mux_space_id, "name": null},
                "memberId": member_id,
                "closeSession": true,
                "deleteHistory": true,
            }),
        )?;
        if response.result_type != "mux" {
            return Err(());
        }
        let mux: Mux = serde_json::from_str(response.result.get()).map_err(|_| ())?;
        if mux.mux_space_id != self.mux_space_id || mux.name != self.mux_name {
            return Err(());
        }
        for member in &mux.members {
            if member.member_id == *member_id
                || member.value()?["session"]["sessionId"] == session_id
            {
                return Err(());
            }
        }
        Ok(true)
    }

    pub(crate) fn create_session<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        source_session_id: Option<&str>,
        continuity_id: &str,
        title: &str,
        request_id: &str,
    ) -> Result<CreateSessionResult, ()> {
        if !identifier(continuity_id, 512) || title.trim().is_empty() || title.chars().count() > 256
        {
            return Err(());
        }
        let template = match source_session_id {
            Some(id) => self.session_templates.get(id).ok_or(())?,
            None => match &self.default_template {
                Some(template) => template,
                None => {
                    return Ok(CreateSessionResult::Rejected(
                        "workspace_not_selected".to_owned(),
                    ))
                }
            },
        };
        let response = request(
            channel,
            "mux/member/open",
            request_id,
            json!({
                "selector": {"muxSpaceId": null, "name": self.mux_name},
                "session": {
                    "productId": template.product_id,
                    "continuityId": continuity_id,
                    "scope": template.scope,
                    "scopeFingerprint": template.scope_fingerprint,
                    "title": title,
                    "sessionId": null,
                },
            }),
        )?;
        decode_create_result(
            &response.result_type,
            &response.result,
            &self.mux_name,
            continuity_id,
            &template.product_id,
        )
    }

    fn app_payload(&self, session_id: &str) -> Result<Value, ()> {
        let member_id = self.members.get(session_id).ok_or(())?;
        let generation: Value =
            serde_json::from_str(&self.controller_generation).map_err(|_| ())?;
        Ok(json!({
            "attachmentId": self.attachment_id,
            "controllerGeneration": generation,
            "memberId": member_id,
        }))
    }

    pub(crate) fn models<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        request_id: &str,
    ) -> Result<ModelControlResult, ()> {
        self.model_request(
            channel,
            "session/models",
            session_id,
            None,
            None,
            request_id,
        )
    }

    pub(crate) fn select_model<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        model_id: &str,
        thinking_level: Option<&str>,
        request_id: &str,
    ) -> Result<ModelControlResult, ()> {
        if model_id.trim().is_empty()
            || model_id.chars().count() > 512
            || thinking_level.is_some_and(|level| !THINKING_LEVELS.contains(&level))
        {
            return Err(());
        }
        self.model_request(
            channel,
            "session/model/select",
            session_id,
            Some(model_id),
            thinking_level,
            request_id,
        )
    }

    fn model_request<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        operation: &str,
        session_id: &str,
        model_id: Option<&str>,
        thinking_level: Option<&str>,
        request_id: &str,
    ) -> Result<ModelControlResult, ()> {
        let mut payload = self.app_payload(session_id)?;
        if let Some(model_id) = model_id {
            payload["modelId"] = Value::String(model_id.to_owned());
        }
        if let Some(level) = thinking_level {
            payload["thinkingLevel"] = Value::String(level.to_owned());
        }
        let response = request(channel, operation, request_id, payload)?;
        decode_model_result(&response.result_type, &response.result)
    }

    pub fn service_instance_id(&self) -> &str {
        &self.instance
    }

    fn payload(&self, session_id: &str) -> Result<Value, ()> {
        Ok(json!({
            "control": self.app_payload(session_id)?,
            "expectedInstanceId": self.instance,
        }))
    }

    pub(crate) fn submit<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        submission_id: &str,
        input: (&str, Vec<Value>),
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        let (text, refs) = input;
        if (text.trim().is_empty() && refs.is_empty())
            || refs.len() > 4
            || text.chars().count() > 262_144
        {
            return Err(());
        }
        let mut payload = self.submission_payload(session_id, submission_id)?;
        payload["text"] = Value::String(text.to_owned());
        if !refs.is_empty() {
            payload["resourceRefs"] = Value::Array(refs);
        }
        let result = execution_request(channel, "execution/submit", request_id, payload)?;
        self.record_result(result, session_id, Some(submission_id))
    }

    pub(crate) fn resource<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        query: Value,
        request_id: &str,
    ) -> Result<Value, ()> {
        let mut payload = self.payload(session_id)?;
        payload["resourceQuery"] = query;
        let result = execution_request(channel, "session/resource", request_id, payload)?;
        if let Some(error) = rejected_result(&result)? {
            return Ok(json!({"error": error}));
        }
        if result["resultType"] != "session_resource" || !result["result"].is_object() {
            return Err(());
        }
        Ok(result["result"].clone())
    }

    pub(crate) fn start_goal<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        submission_id: &str,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        let payload = self.submission_payload(session_id, submission_id)?;
        let result = execution_request(channel, "execution/goal_start", request_id, payload)?;
        self.record_result(result, session_id, Some(submission_id))
    }

    fn submission_payload(&self, session_id: &str, submission_id: &str) -> Result<Value, ()> {
        if !identifier(submission_id, 128) {
            return Err(());
        }
        let mut payload = self.payload(session_id)?;
        payload["submissionId"] = Value::String(submission_id.to_owned());
        Ok(payload)
    }

    pub(crate) fn find_submission<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        submission_id: &str,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        let payload = self.submission_payload(session_id, submission_id)?;
        let result = execution_request(channel, "execution/find_submission", request_id, payload)?;
        if result["resultType"] == "not_found" {
            projection::control_bridge("not_found", &result.to_string())?;
            return Ok(ControlResult::Missing);
        }
        self.record_result(result, session_id, Some(submission_id))
    }

    pub(crate) fn respond_interaction<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        interaction_id: &str,
        outcome: InteractionOutcome,
        request_id: &str,
    ) -> Result<ControlResult, ()> {
        let response = request(
            channel,
            "interaction/respond",
            request_id,
            RespondInteraction {
                attachment_id: &self.attachment_id,
                controller_generation: serde_json::from_str(&self.controller_generation)
                    .map_err(|_| ())?,
                member_id: self.members.get(session_id).ok_or(())?,
                interaction_id,
                outcome,
            },
        )?;
        if let Some(code) = decode_app_error(&response.result_type, &response.result)? {
            return Ok(ControlResult::Rejected(code));
        }
        if response.result_type != "ack" {
            return Err(());
        }
        let ack: serde_json::Map<String, Value> =
            serde_json::from_str(response.result.get()).map_err(|_| ())?;
        if !ack.is_empty() {
            return Err(());
        }
        Ok(ControlResult::Accepted)
    }

    pub(crate) fn interactive_goal<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        target: Option<&str>,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        let mut payload = self.payload(session_id)?;
        let operation = if let Some(target) = target {
            if target.trim().is_empty() || target.len() > 16_384 {
                return Ok(None);
            }
            payload["goalTarget"] = Value::String(target.to_owned());
            "session/interactive_goal_create"
        } else {
            "session/interactive_goal_status"
        };
        let result = execution_request(channel, operation, request_id, payload)?;
        decode_interactive_goal(result, None)
    }

    pub(crate) fn control_interactive_goal<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        command: InteractiveGoalCommand,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        if !identifier(&command.goal_id, 128) || !identifier(&command.command_id, 128) {
            return Ok(None);
        }
        let mut payload = self.payload(session_id)?;
        payload["goalId"] = json!(command.goal_id);
        payload["commandId"] = json!(command.command_id);
        payload["action"] = json!(command.action);
        let result = execution_request(
            channel,
            "session/interactive_goal_command",
            request_id,
            payload,
        )?;
        decode_interactive_goal(result, Some(&command))
    }

    pub(crate) fn interactive_goal_recovery<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        let payload = self.payload(session_id)?;
        let result = execution_request(
            channel,
            "session/interactive_goal_recovery",
            request_id,
            payload,
        )?;
        if rejected_result(&result)?.is_some() {
            return Ok(None);
        }
        let mut checked =
            projection::control_bridge("interactive_goal_recovery", &result.to_string())?;
        Ok(Some(checked["result"].take()))
    }

    pub(crate) fn interactive_goal_review<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        goal_id: &str,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        if !identifier(goal_id, 128) {
            return Ok(None);
        }
        let mut payload = self.payload(session_id)?;
        payload["goalId"] = json!(goal_id);
        let result = execution_request(
            channel,
            "session/interactive_goal_review",
            request_id,
            payload,
        )?;
        if rejected_result(&result)?.is_some() {
            return Ok(None);
        }
        let mut checked =
            projection::control_bridge("interactive_goal_review", &result.to_string())?;
        if checked["result"]["goalId"] != goal_id {
            return Err(());
        }
        Ok(Some(checked["result"].take()))
    }

    pub(crate) fn submit_interactive_goal_review<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        review: InteractiveGoalReviewSubmission,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        let valid_reason = match (review.decision, &review.reason) {
            (InteractiveGoalReviewDecision::Accept, None) => true,
            (InteractiveGoalReviewDecision::Reject, Some(value)) => {
                !value.trim().is_empty() && value.len() <= 4096
            }
            _ => false,
        };
        if !valid_reason
            || !identifier(&review.goal_id, 128)
            || !identifier(&review.command_id, 128)
            || !projection::review_token(&review.review_token)
        {
            return Ok(None);
        }
        let mut payload = self.payload(session_id)?;
        let wire = serde_json::to_value(&review).map_err(|_| ())?;
        payload
            .as_object_mut()
            .ok_or(())?
            .extend(wire.as_object().ok_or(())?.clone());
        let result = execution_request(
            channel,
            "session/interactive_goal_review_submit",
            request_id,
            payload,
        )?;
        let view = decode_interactive_goal(result, None)?;
        check_goal_receipt(
            view,
            &review.goal_id,
            &review.command_id,
            json!(review.decision),
        )
    }

    pub(crate) fn goal_progress<R: Read, W: Write>(
        &self,
        channel: &mut Channel<R, W>,
        session_id: &str,
        execution_id: &str,
        request_id: &str,
    ) -> Result<Option<Value>, ()> {
        if !identifier(execution_id, 128) {
            return Err(());
        }
        let mut payload = self.payload(session_id)?;
        payload["executionId"] = Value::String(execution_id.to_owned());
        payload["includeBatches"] = Value::Bool(true);
        let result = execution_request(channel, "execution/goal_progress", request_id, payload)?;
        decode_goal_progress(result, execution_id)
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
        let execution_id = record["state"]["executionId"].as_str().ok_or(())?;
        Ok(ControlResult::Submitted(execution_id.to_owned()))
    }
}

const THINKING_LEVELS: [&str; 7] = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];

pub(super) fn decode_model_result(
    result_type: &str,
    result: &RawValue,
) -> Result<ModelControlResult, ()> {
    if let Some(code) = decode_app_error(result_type, result)? {
        return Ok(ModelControlResult::Rejected(code));
    }
    if result_type != "sessionModels" {
        return Err(());
    }
    let value: Value = serde_json::from_str(result.get()).map_err(|_| ())?;
    let root = value.as_object().ok_or(())?;
    if !root.contains_key("currentId")
        || !root.contains_key("models")
        || root
            .keys()
            .any(|key| !["currentId", "models", "thinking"].contains(&key.as_str()))
    {
        return Err(());
    }
    if !root["models"].is_array()
        || (!root["currentId"].is_null() && !root["currentId"].is_string())
    {
        return Err(());
    }
    if let Some(thinking) = root.get("thinking") {
        let settings = thinking.as_object().ok_or(())?;
        let current = settings.get("currentLevel").ok_or(())?;
        let levels = settings
            .get("availableLevels")
            .and_then(Value::as_array)
            .ok_or(())?;
        if settings.len() != 2
            || root["currentId"].is_null()
            || levels.is_empty()
            || levels.len() > THINKING_LEVELS.len()
            || (!current.is_null() && !levels.contains(current))
            || levels
                .iter()
                .enumerate()
                .any(|(index, level)| levels[..index].contains(level))
            || levels.iter().any(|level| {
                !level
                    .as_str()
                    .is_some_and(|name| THINKING_LEVELS.contains(&name))
            })
        {
            return Err(());
        }
    }
    Ok(ModelControlResult::Accepted(value))
}

pub fn definitive_create_rejection(code: &str) -> bool {
    matches!(
        code,
        "workspace_not_selected"
            | "invalid_request"
            | "not_found"
            | "product_mismatch"
            | "already_attached"
            | "session_unavailable"
    )
}

fn decode_create_result(
    result_type: &str,
    result: &RawValue,
    mux_name: &str,
    continuity_id: &str,
    product_id: &str,
) -> Result<CreateSessionResult, ()> {
    if let Some(code) = decode_app_error(result_type, result)? {
        return Ok(CreateSessionResult::Rejected(code));
    }
    if result_type != "mux" {
        return Err(());
    }
    let mux: Mux = serde_json::from_str(result.get()).map_err(|_| ())?;
    if mux.name != mux_name
        || !identifier(&mux.mux_space_id, 512)
        || !positive(&mux.revision)
        || mux.members.len() > 128
    {
        return Err(());
    }
    for member in &mux.members {
        let value = member.value()?;
        let identity = &value["session"];
        if identity["continuityId"] == continuity_id && identity["productId"] == product_id {
            return Ok(CreateSessionResult::Accepted(
                identity["sessionId"].as_str().ok_or(())?.to_owned(),
            ));
        }
    }
    Err(())
}

pub(super) fn decode_app_error(result_type: &str, result: &RawValue) -> Result<Option<String>, ()> {
    if result_type != "error" {
        return Ok(None);
    }
    let error: Value = serde_json::from_str(result.get()).map_err(|_| ())?;
    let code = error.get("code").and_then(Value::as_str).ok_or(())?;
    if !identifier(code, 128) {
        return Err(());
    }
    Ok(Some(code.to_owned()))
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

fn decode_interactive_goal(
    result: Value,
    expected: Option<&InteractiveGoalCommand>,
) -> Result<Option<Value>, ()> {
    if rejected_result(&result)?.is_some() {
        return Ok(None);
    }
    let mut checked = projection::control_bridge("interactive_goal", &result.to_string())?;
    let view = checked["result"].take();
    if let Some(command) = expected {
        return check_goal_receipt(
            Some(view),
            &command.goal_id,
            &command.command_id,
            json!(command.action),
        );
    }
    Ok(Some(view))
}

fn check_goal_receipt(
    view: Option<Value>,
    goal_id: &str,
    command_id: &str,
    action: Value,
) -> Result<Option<Value>, ()> {
    if view.as_ref().is_some_and(|value| {
        value["goalId"] != goal_id
            || value["command"]["commandId"] != command_id
            || value["command"]["action"] != action
    }) {
        return Err(());
    }
    Ok(view)
}

fn decode_goal_progress(result: Value, execution_id: &str) -> Result<Option<Value>, ()> {
    if rejected_result(&result)?.is_some() {
        return Ok(None);
    }
    let mut checked = projection::control_bridge("goal_progress", &result.to_string())?;
    if checked["result"]["executionId"].as_str() != Some(execution_id) {
        return Err(());
    }
    Ok(Some(checked["result"].take()))
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AttachmentEvents {
    events: Vec<AttachmentEvent>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AttachmentEvent {
    attachment_id: String,
    member_id: String,
    protocol_version: String,
    event: SourceEvent,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SourceEvent {
    cursor: Box<RawValue>,
    session_id: String,
    kind: String,
    interaction_id: Option<String>,
    text: Option<String>,
}

fn cursor_order(left: &str, right: &str) -> std::cmp::Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

fn approval_snapshots(snapshots: Vec<Value>, readers: &[EventReader]) -> Vec<Value> {
    snapshots
        .into_iter()
        .zip(readers)
        .map(|(mut value, reader)| {
            let approvals = reader
                .approvals
                .iter()
                .map(|(id, text)| json!({"interactionId": id, "text": text}))
                .collect();
            let mut snapshot = value["result"].take();
            snapshot["pendingApprovals"] = Value::Array(approvals);
            snapshot
        })
        .collect()
}

// Inputs have passed the independent wire validators. Keep content and metadata
// watermarks separate, and never coerce arbitrary-size source cursors to floats.
#[derive(Clone)]
struct EventReader {
    session_id: Value,
    cursor: String,
    revision: u64,
    approvals: BTreeMap<String, String>,
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
            approvals: BTreeMap::new(),
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
    fn rebase(&mut self, snapshot: &Value) -> Result<(), ()> {
        if !self.valid {
            return Err(());
        }
        let source = &snapshot["result"]["source"]["source"];
        let cursor = source["cursor"].as_str().ok_or(())?;
        let revision = snapshot["result"]["executions"]["revision"]
            .as_u64()
            .ok_or(())?;
        if source["identity"]["sessionId"] != self.session_id
            || cursor.len() < self.cursor.len()
            || (cursor.len() == self.cursor.len() && cursor < self.cursor.as_str())
            || revision < self.revision
        {
            return Err(());
        }
        self.cursor = cursor.to_owned();
        self.revision = revision;
        Ok(())
    }
    fn advance(&mut self, events: &Value) -> Result<(), ()> {
        for event in events["result"]["events"].as_array().ok_or(())? {
            if let Some(content) = event.get("source") {
                self.advance_content(content)?;
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

    fn advance_content(&mut self, content: &Value) -> Result<(), ()> {
        let cursor = content["cursor"].as_str().ok_or(())?;
        if content["sessionId"] != self.session_id || cursor != successor(&self.cursor) {
            return Err(());
        }
        self.apply_interaction(
            content["kind"].as_str().ok_or(())?,
            content["interactionId"].as_str(),
            content["text"].as_str(),
        )?;
        self.cursor = cursor.to_owned();
        Ok(())
    }

    fn apply_covered_interaction(&mut self, event: SourceEvent, previous: &str) -> Result<(), ()> {
        if self.session_id != event.session_id || !positive(&event.cursor) {
            return Err(());
        }
        let cursor = event.cursor.get();
        if cursor_order(cursor, previous).is_gt() && !cursor_order(cursor, &self.cursor).is_gt() {
            self.apply_interaction(
                &event.kind,
                event.interaction_id.as_deref(),
                event.text.as_deref(),
            )?;
        }
        Ok(())
    }

    fn apply_interaction(
        &mut self,
        kind: &str,
        interaction_id: Option<&str>,
        text: Option<&str>,
    ) -> Result<(), ()> {
        match kind {
            "interaction_requested" => {
                let id = interaction_id.filter(|id| identifier(id, 512)).ok_or(())?;
                let text = text
                    .filter(|text| !text.trim().is_empty() && text.chars().count() <= 262_144)
                    .ok_or(())?;
                self.approvals
                    .entry(id.to_owned())
                    .or_insert_with(|| text.to_owned());
                if self.approvals.len() > 16 {
                    return Err(());
                }
            }
            "interaction_dismissed" => {
                let id = interaction_id.filter(|id| identifier(id, 512)).ok_or(())?;
                self.approvals.remove(id);
            }
            _ => {}
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn goal_start_uses_the_current_member_and_validates_the_submission_record() {
        let authority = ControlAuthority {
            attachment_id: "attachment".into(),
            controller_generation: "1".into(),
            instance: "instance".into(),
            mux_name: "goal".into(),
            mux_space_id: "mux".into(),
            members: BTreeMap::from([("session".into(), "member".into())]),
            session_templates: BTreeMap::new(),
            default_template: None,
        };
        assert_eq!(
            authority
                .submission_payload("session", "submission")
                .unwrap(),
            json!({
                "control": {"attachmentId": "attachment", "controllerGeneration": 1, "memberId": "member"},
                "expectedInstanceId": "instance",
                "submissionId": "submission",
            }),
        );
        assert!(authority.submission_payload("other", "submission").is_err());
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../../tests/appserver/fixtures/execution_v1.json"
        ))
        .unwrap();
        let record = &fixture["accepted"];
        assert!(matches!(
            authority.record_result(record.clone(), "session", Some("submission")),
            Ok(ControlResult::Submitted(id)) if id == "execution"
        ));
        assert!(authority
            .record_result(record.clone(), "session", Some("other"))
            .is_err());
        assert!(authority
            .record_result(record.clone(), "other", Some("submission"))
            .is_err());
        let mut stale = record.clone();
        stale["result"]["serviceInstanceId"] = json!("old-instance");
        assert!(authority
            .record_result(stale, "session", Some("submission"))
            .is_err());
    }

    #[test]
    fn interactive_goal_reply_binds_goal_command_and_action() {
        let request = InteractiveGoalCommand {
            goal_id: "goal-1".into(),
            command_id: "command-1".into(),
            action: super::super::InteractiveGoalAction::Step,
        };
        let reply = json!({
            "protocolVersion": "loushang.execution/v1", "requestId": "1",
            "resultType": "interactive_goal",
            "result": {
                "availability": "present", "goalId": "goal-1", "status": "active",
                "revision": 1, "epoch": 1, "executionUnresolved": false,
                "command": { "commandId": "command-1", "action": "step", "status": "running" },
            },
        });
        assert_eq!(
            decode_interactive_goal(reply.clone(), Some(&request)),
            Ok(Some(reply["result"].clone()))
        );
        for field in [
            "/result/goalId",
            "/result/command/commandId",
            "/result/command/action",
        ] {
            let mut mismatched = reply.clone();
            *mismatched.pointer_mut(field).unwrap() = json!("run");
            assert!(decode_interactive_goal(mismatched, Some(&request)).is_err());
        }
    }

    #[test]
    fn goal_progress_reply_is_bound_to_the_requested_execution() {
        let reply = json!({
            "protocolVersion": "loushang.execution/v1",
            "requestId": "3",
            "resultType": "goal_progress",
            "result": {
                "executionId": "exec-1", "presence": "present", "goalId": "calculator",
                "status": "paused", "reasonCode": "model_budget", "validity": "not_checked",
                "executionUnresolved": false, "advances": 1, "modelCalls": 2, "batchCount": 0, "batches": [],
            },
        });
        assert!(decode_goal_progress(reply.clone(), "exec-2").is_err());
        assert_eq!(
            decode_goal_progress(reply.clone(), "exec-1"),
            Ok(Some(reply["result"].clone()))
        );
        assert_eq!(
            decode_goal_progress(
                json!({
                    "protocolVersion": "loushang.execution/v1",
                    "requestId": "3",
                    "resultType": "app_failure",
                    "result": {"code": "operation_unavailable"},
                }),
                "exec-1"
            ),
            Ok(None),
        );
    }

    #[test]
    fn session_model_result_keeps_default_and_both_top_efforts() {
        let raw = RawValue::from_string(
            json!({
                "currentId": "provider:endpoint:model",
                "models": [],
                "thinking": {
                    "currentLevel": null,
                    "availableLevels": ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
                }
            })
            .to_string(),
        )
        .unwrap();
        let ModelControlResult::Accepted(result) =
            decode_model_result("sessionModels", &raw).unwrap()
        else {
            panic!("model result was rejected");
        };
        assert!(result["thinking"]["currentLevel"].is_null());
        assert_eq!(result["thinking"]["availableLevels"][6], "max");
    }

    #[test]
    fn model_capability_rejection_is_semantic_not_transport_failure() {
        let raw = RawValue::from_string(r#"{"code":"operation_unavailable"}"#.to_owned()).unwrap();
        match decode_model_result("error", &raw).unwrap() {
            ModelControlResult::Rejected(code) => assert_eq!(code, "operation_unavailable"),
            ModelControlResult::Accepted(_) => panic!("error response was accepted"),
        }
        assert!(decode_model_result("unexpected", &raw).is_err());
    }

    #[test]
    fn member_creation_distinguishes_rejection_from_uncertain_cleanup() {
        assert!(definitive_create_rejection("session_unavailable"));
        assert!(!definitive_create_rejection("cleanup_incomplete"));
        assert!(!definitive_create_rejection("operation_unavailable"));
    }

    #[test]
    fn created_session_is_identified_from_the_validated_mux_result() {
        let fingerprint = "a".repeat(64);
        let raw = RawValue::from_string(
            json!({
                "muxSpaceId": "mux-1",
                "name": "gui",
                "revision": 2,
                "members": [{
                    "memberId": "member-1",
                    "session": {
                        "productId": "coding",
                        "continuityId": "continuity-1",
                        "sessionId": "session-1",
                        "scope": "cwd",
                        "scopeFingerprint": fingerprint,
                    },
                    "title": "New Session",
                    "position": 1,
                }],
            })
            .to_string(),
        )
        .unwrap();
        match decode_create_result("mux", &raw, "gui", "continuity-1", "coding").unwrap() {
            CreateSessionResult::Accepted(session_id) => assert_eq!(session_id, "session-1"),
            CreateSessionResult::Rejected(code) => panic!("unexpected rejection: {code}"),
        }

        let error =
            RawValue::from_string(r#"{"code":"operation_unavailable"}"#.to_owned()).unwrap();
        assert!(matches!(
            decode_create_result("error", &error, "gui", "continuity-1", "coding").unwrap(),
            CreateSessionResult::Rejected(code) if code == "operation_unavailable"
        ));
    }

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
        let batch = |cursors: &[&str]| json!({"result":{"events":cursors.iter().map(|c| json!({"source":{"sessionId":"s","kind":"status","cursor":c}})).collect::<Vec<_>>()}});
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
    fn authoritative_snapshot_rebases_both_event_watermarks() {
        let initial = json!({"result":{"source":{"source":{"cursor":"4", "identity":{"sessionId":"s"}}},"executions":{"revision":3}}});
        let mut reader = EventReader::new(&initial).unwrap();
        let metadata = json!({"result":{"events":[{"revision":4}]}});
        reader.apply(&metadata).unwrap();
        let cut = json!({"result":{"source":{"source":{"cursor":"5", "identity":{"sessionId":"s"}}},"executions":{"revision":5}}});
        reader.rebase(&cut).unwrap();
        assert_eq!(reader.cursor, "5");
        assert_eq!(reader.revision, 5);
        assert!(reader
            .apply(&json!({"result":{"events":[
                {"source":{"sessionId":"s","kind":"status","cursor":"6"}}, {"revision":6}
            ]}}))
            .is_ok());
        assert!(reader.rebase(&initial).is_err());
    }
    #[test]
    fn approval_request_is_deduplicated_and_only_a_matching_dismissal_removes_it() {
        let mut reader = EventReader::new(&json!({"result": {
            "source":{"source":{"identity":{"sessionId":"s"},"cursor":"0"}},
            "executions":{"revision":0}
        }}))
        .unwrap();
        let event = |cursor: &str, kind: &str, id: &str, text: Option<&str>| {
            json!({
                "source":{"sessionId":"s","cursor":cursor,"kind":kind,"interactionId":id,"text":text}
            })
        };
        reader
            .apply(&json!({"result":{"events":[
                event("1", "interaction_requested", "one", Some("Preview")),
                event("2", "interaction_requested", "one", Some("Preview")),
                event("3", "interaction_requested", "two", Some("Second")),
                event("4", "interaction_dismissed", "two", None),
            ]}}))
            .unwrap();
        assert_eq!(
            reader.approvals,
            BTreeMap::from([("one".into(), "Preview".into())])
        );
        reader
            .apply(&json!({"result":{"events":[event("5", "interaction_dismissed", "one", None)]}}))
            .unwrap();
        assert!(reader.approvals.is_empty());
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
        let content =
            json!({"source":{"sessionId":"s","kind":"status","cursor":"1000000000000000000000"}});
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
                json!({"source":{"sessionId":"other","kind":"status","cursor":"1000000000000000000000"}})
            ])
        )
        .is_err());
    }
}
