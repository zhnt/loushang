use super::{field, session_control, Result, Target, View};
use crate::app_client::client_directory::{Directory, Request};
use crate::AppClient;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    path::PathBuf,
    time::{Duration, Instant},
};

const CAPACITY: usize = 64;
const DRAFT_AGE: Duration = Duration::from_secs(30 * 60);

#[derive(Default)]
pub(super) struct Grants(HashMap<String, Grant>);

struct Grant {
    target: Target,
    directory: Directory,
    name: String,
    key: String,
    credential: [u8; 32],
    created: Instant,
    session: Option<String>,
    resource: Option<String>,
}

impl Grants {
    pub fn add(&mut self, target: Target, path: PathBuf) -> Result<Value> {
        let Target::Tunnel(root, _) = &target else {
            return Err("operation_unavailable".into());
        };
        let credential = AppClient::tunnel_binding(root).map_err(|_| "connection_failed")?;
        let private = root.canonicalize().map_err(|_| "connection_failed")?;
        if private.starts_with(&path) || path.starts_with(&private) {
            return Err("permission_denied".into());
        }
        self.0
            .retain(|_, grant| grant.session.is_some() || grant.created.elapsed() < DRAFT_AGE);
        if self.0.len() >= CAPACITY {
            return Err("operation_unavailable".into());
        }
        let name = path
            .file_name()
            .and_then(|name| name.to_str())
            .filter(|name| !name.is_empty() && name.chars().count() <= 150)
            .ok_or("resource_unavailable")?
            .to_owned();
        let directory = Directory::open(path).map_err(|_| "resource_unavailable")?;
        let id = random_hex::<16>()?;
        let key = random_hex::<32>()?;
        self.0.insert(
            id.clone(),
            Grant {
                target,
                directory,
                name: name.clone(),
                key,
                credential,
                created: Instant::now(),
                session: None,
                resource: None,
            },
        );
        Ok(json!({"id": id, "name": name}))
    }

    pub fn reference(&mut self, view: &View, input: &Value) -> Result<Value> {
        let session = field(input, "sessionId")?;
        let id = field(input, "grantId")?;
        if self
            .0
            .values()
            .filter(|grant| {
                grant.target == view.target && grant.session.as_deref() == Some(session)
            })
            .count()
            >= 8
            && !self
                .0
                .get(id)
                .is_some_and(|grant| grant.session.as_deref() == Some(session))
        {
            return Err("operation_unavailable".into());
        }
        let grant = self
            .0
            .get_mut(id)
            .filter(|grant| {
                grant.target == view.target && Some(grant.credential) == view.tunnel_binding
            })
            .ok_or("resource_unavailable")?;
        if grant
            .session
            .as_deref()
            .is_some_and(|previous| previous != session)
        {
            return Err("permission_denied".into());
        }
        grant.session = Some(session.to_owned());
        let query = query(
            "clientReference",
            None,
            &grant.key,
            Some(&grant.name),
            None,
            "",
        );
        let result = resource(view, session, query)?;
        if result.get("error").is_some() {
            return Ok(result);
        }
        let reference = &result["resources"][0];
        let resource_id = field(reference, "id")?;
        if reference["source"] != "client_reference"
            || reference["kind"] != "directory"
            || resource_id.len() != 64
            || !resource_id.bytes().all(|c| c.is_ascii_hexdigit())
        {
            return Err("invalid_host_reply".into());
        }
        grant.resource = Some(resource_id.to_owned());
        Ok(result)
    }

    pub fn revoke(&mut self, target: &Target, selector: &str) -> bool {
        let before = self.0.len();
        self.0.retain(|id, grant| {
            &grant.target != target
                || (id != selector && grant.resource.as_deref() != Some(selector))
        });
        self.0.len() != before
    }

    pub fn serve(&self, view: &View, snapshot: &Value) {
        let Some(sessions) = snapshot["sessions"].as_array() else {
            return;
        };
        for grant in self.0.values().filter(|grant| {
            grant.target == view.target && Some(grant.credential) == view.tunnel_binding
        }) {
            let (Some(session), Some(id)) = (&grant.session, &grant.resource) else {
                continue;
            };
            let running = sessions.iter().any(|row| {
                let source = &row["source"]["source"];
                source["identity"]["sessionId"] == *session && source["running"] == true
            });
            if running {
                Self::serve_one(view, session, id, grant);
            }
        }
    }

    fn serve_one(view: &View, session: &str, id: &str, grant: &Grant) {
        let Ok(reply) = resource(
            view,
            session,
            query("proxyPoll", Some(id), &grant.key, None, None, ""),
        ) else {
            return;
        };
        let Some(request) = reply.get("proxyRequest") else {
            return;
        };
        let Ok(request) = serde_json::from_value::<Request>(request.clone()) else {
            return;
        };
        let data = grant
            .directory
            .respond(&request)
            .map_or_else(|_| String::new(), |result| result.to_string());
        let _ = resource(
            view,
            session,
            query(
                "proxyComplete",
                Some(id),
                &grant.key,
                None,
                Some(&request.id),
                &data,
            ),
        );
    }
}

fn random_hex<const N: usize>() -> Result<String> {
    let mut bytes = [0; N];
    getrandom::getrandom(&mut bytes).map_err(|_| "operation_unavailable")?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

fn resource(view: &View, session: &str, query: Value) -> Result<Value> {
    session_control(
        view,
        "resource",
        &json!({"sessionId": session, "query": query}),
    )
}

fn query(
    action: &str,
    id: Option<&str>,
    key: &str,
    name: Option<&str>,
    request: Option<&str>,
    data: &str,
) -> Value {
    let mut value = json!({
        "action": action, "resourceId": id, "offset": 0, "totalBytes": 0,
        "mediaType": "", "data": data, "proxyKey": key
    });
    if let Some(name) = name {
        value["name"] = json!(name);
    }
    if let Some(request) = request {
        value["requestId"] = json!(request);
    }
    value
}
