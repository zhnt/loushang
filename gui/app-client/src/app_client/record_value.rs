//! Closed service-record value decoder; native file admission stays separate.
use serde::Deserialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Record {
    schema_version: String,
    profile: String,
    protocol_version: String,
    pub endpoint: String,
    application_id: String,
    product_id: String,
    pub instance: String,
    port: u16,
    scopes: Vec<Scope>,
    capabilities: Vec<String>,
    key: String,
}

#[cfg(test)]
mod creation_tests {
    use super::*;

    #[test]
    fn creation_uses_admitted_workspace_even_when_home_is_first() {
        let mut value: Value = serde_json::from_str(include_str!(
            "../../../contracts/fixtures/local-record.json"
        ))
        .unwrap();
        value["scopes"] = json!([
            {"scope":"user_home","fingerprint":"c".repeat(64)},
            {"scope":"cwd","fingerprint":"b".repeat(64)}
        ]);
        let record = Record::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert_eq!(
            record.creation_context(),
            Some(("coding", "cwd", "b".repeat(64).as_str()))
        );
        value["scopes"].as_array_mut().unwrap().pop();
        let record = Record::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert_eq!(
            record.creation_context(),
            Some(("coding", "user_home", "c".repeat(64).as_str()))
        );
    }
    #[test]
    fn managed_host_without_workspace_attaches_without_a_creation_context() {
        let mut value: Value = serde_json::from_str(include_str!(
            "../../../contracts/fixtures/local-record.json"
        ))
        .unwrap();
        value["scopes"] = json!([]);
        assert!(Record::decode(&serde_json::to_vec(&value).unwrap()).is_err());
        value["capabilities"]
            .as_array_mut()
            .unwrap()
            .push(json!("mux_management"));
        let record = Record::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(record.creation_context().is_none());
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scope {
    scope: String,
    fingerprint: String,
}

fn identifier(value: &str, maximum: usize, lower: bool) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value.bytes().all(|byte| {
            (byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
                && (!lower || !byte.is_ascii_uppercase())
        })
}
fn hex(value: &str, size: usize) -> bool {
    value.len() == size
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}
impl Record {
    /// Default creation uses the admitted workspace, falling back to the sole
    /// home scope when no workspace scope was published. No path is inferred.
    pub(crate) fn creation_context(&self) -> Option<(&str, &str, &str)> {
        let scope = self
            .scopes
            .iter()
            .find(|scope| scope.scope == "cwd")
            .or_else(|| self.scopes.first())?;
        Some((&self.product_id, &scope.scope, &scope.fingerprint))
    }
    pub fn port(&self) -> u16 {
        self.port
    }
    pub fn filename(endpoint: &str) -> Result<String, ()> {
        if !identifier(endpoint, 64, false) {
            return Err(());
        }
        Ok(format!("{:x}.json", Sha256::digest(endpoint.as_bytes())))
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, ()> {
        if bytes.is_empty() || bytes.len() > 8192 {
            return Err(());
        }
        let value: Self = serde_json::from_slice(bytes).map_err(|_| ())?;
        if value.schema_version != "loushang.appserver.local-record/v1"
            || value.profile != "local-detachable/v1"
            || value.protocol_version != "loushang.app/v1"
            || !identifier(&value.endpoint, 64, false)
            || !identifier(&value.application_id, 128, true)
            || !identifier(&value.product_id, 128, true)
            || !hex(&value.instance, 32)
            || value.port == 0
            || !hex(&value.key, 64)
            || (value.scopes.is_empty()
                && !value.capabilities.iter().any(|cap| cap == "mux_management"))
            || value.scopes.len() > 2
            || value.scopes.iter().any(|scope| {
                !["cwd", "user_home"].contains(&scope.scope.as_str())
                    || !hex(&scope.fingerprint, 64)
            })
            || (value.scopes.len() == 2 && value.scopes[0].scope == value.scopes[1].scope)
        {
            return Err(());
        }
        value.semantic_profile()?;
        Ok(value)
    }
    pub fn semantic_profile(&self) -> Result<String, ()> {
        // Match the Python closed capability algebra, including its canonical order.
        let caps: Vec<_> = self.capabilities.iter().map(String::as_str).collect();
        if !caps.starts_with(&["named_mux", "text_turns", "approvals"]) {
            return Err(());
        }
        let mut index = 3;
        let mut take = |name: &str| {
            if caps.get(index) == Some(&name) {
                index += 1;
                true
            } else {
                false
            }
        };
        let discovery = take("session_discovery");
        let execution = take("session_execution");
        let managed = take("mux_management");
        let closure = take("mux_closure");
        let resume = take("resume_input_lookup");
        if index != caps.len() || (closure && !managed) || (resume && !execution) {
            return Err(());
        }
        Ok(format!(
            "local-detachable{}{}{}{}{version}",
            if discovery { "-discovery" } else { "" },
            if resume { "-resume" } else { "" },
            if execution { "-execution" } else { "" },
            if managed { "-managed" } else { "" },
            version = if closure { "/v2" } else { "/v1" }
        ))
    }
    pub fn supports_execution(&self) -> bool {
        self.capabilities
            .iter()
            .any(|cap| cap == "session_execution")
    }
    pub fn public(&self) -> Value {
        json!({"schemaVersion": self.schema_version, "profile": self.profile,
            "protocolVersion": self.protocol_version, "endpoint": self.endpoint,
            "applicationId": self.application_id, "productId": self.product_id,
            "instance": self.instance, "port": self.port,
            "scopes": self.scopes.iter().map(|scope| json!({"scope":scope.scope,"fingerprint":scope.fingerprint})).collect::<Vec<_>>(),
            "capabilities": self.capabilities})
    }
    pub fn digest(&self) -> Result<[u8; 32], ()> {
        // Validated public fields are ASCII; Value maps use sorted canonical keys.
        Ok(Sha256::digest(serde_json::to_vec(&self.public()).map_err(|_| ())?).into())
    }
    pub fn key(&self) -> Result<[u8; 32], ()> {
        let mut key = [0; 32];
        for (index, byte) in key.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&self.key[index * 2..index * 2 + 2], 16).map_err(|_| ())?;
        }
        Ok(key)
    }
    pub fn selected(&self, endpoint: &str, profile: &str) -> Result<Value, ()> {
        if endpoint != self.endpoint || self.semantic_profile()? != profile {
            return Err(());
        }
        Ok(
            json!({"public": self.public(), "semanticProfile": self.semantic_profile()?,
            "recordDigest": format!("{:x}", Sha256::digest(serde_json::to_vec(&self.public()).map_err(|_| ())?)),
            "filename": Self::filename(endpoint)?}),
        )
    }
}
