//! Offline C1 probe only: not a production transport, decoder or Tauri command.
use serde::{Deserialize, Serialize};
use serde_json::{json, value::RawValue, Value};
use std::io::{self, BufRead};
mod projection;
// Compile the generated candidate DTOs without treating them as wire decoders.
#[allow(dead_code)]
#[rustfmt::skip]
#[path = "../../generated/bridge.rs"]
mod generated;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Submit {
    protocol_version: String,
    request_id: String,
    operation: String,
    payload: Payload,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Payload {
    control: Control,
    expected_instance_id: String,
    submission_id: String,
    text: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Control {
    attachment_id: String,
    controller_generation: Box<RawValue>,
    member_id: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Failure {
    protocol_version: String,
    request_id: String,
    result_type: String,
    result: FailureCode,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FailureCode {
    code: String,
}
#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Hello {
    protocol_version: String,
    execution_version: String,
    profile: String,
    service_instance_id: String,
    restart_recovery: bool,
    submission_retention: String,
}
fn identifier(value: &str, max: usize) -> bool {
    !value.is_empty()
        && value.len() <= max
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._~-".contains(&c))
}
fn bridge(kind: &str, wire: &str, profile: Option<&str>) -> Result<Value, ()> {
    if wire.len() > 1_048_576 {
        return Err(());
    }
    if kind == "snapshot" || kind == "events" {
        projection::bridge(kind, wire)
    } else if kind == "hello" {
        let hello: Hello = serde_json::from_str(wire).map_err(|_| ())?;
        if hello.protocol_version != "loushang.app/v1"
            || hello.execution_version != "loushang.execution/v1"
            || Some(hello.profile.as_str()) != profile
            || !identifier(&hello.service_instance_id, 128)
            || hello.restart_recovery
            || hello.submission_retention != "service_instance_lifetime"
        {
            return Err(());
        }
        // Value's sorted map produces the same compact, ASCII-value hello
        // representation as Python execution_hello. Whitespace is not ignored.
        let value = serde_json::to_value(hello).map_err(|_| ())?;
        if serde_json::to_vec(&value).map_err(|_| ())? != wire.as_bytes() {
            return Err(());
        }
        Ok(value)
    } else if kind == "submit" {
        let call: Submit = serde_json::from_str(wire).map_err(|_| ())?;
        let p = &call.payload;
        let c = &p.control;
        let generation = c.controller_generation.get();
        if call.protocol_version != "loushang.execution/v1"
            || call.operation != "execution/submit"
            || !identifier(&call.request_id, 128)
            || !identifier(&p.expected_instance_id, 128)
            || !identifier(&p.submission_id, 128)
            || !identifier(&c.attachment_id, 512)
            || !identifier(&c.member_id, 512)
            || generation.is_empty()
            || generation.starts_with('0')
            || !generation.bytes().all(|c| c.is_ascii_digit())
            || p.text.trim().is_empty()
            || p.text.chars().count() > 262_144
        {
            return Err(());
        }
        Ok(
            json!({"protocolVersion": call.protocol_version, "requestId": call.request_id,
            "operation": call.operation, "payload": {"control": {
                "attachmentId": c.attachment_id, "memberId": c.member_id,
                "controllerGeneration": generation}, "expectedInstanceId": p.expected_instance_id,
                "submissionId": p.submission_id, "text": p.text}}),
        )
    } else if kind == "failure" {
        let value: Failure = serde_json::from_str(wire).map_err(|_| ())?;
        if value.protocol_version != "loushang.execution/v1"
            || value.result_type != "failure"
            || !identifier(&value.request_id, 128)
            || ![
                "service_instance_changed",
                "submission_conflict",
                "submission_ledger_full",
                "execution_busy",
                "execution_not_retained",
                "execution_unsupported",
            ]
            .contains(&value.result.code.as_str())
        {
            return Err(());
        }
        Ok(
            json!({"protocolVersion": value.protocol_version, "requestId": value.request_id,
            "resultType": value.result_type, "result": {"code": value.result.code}}),
        )
    } else {
        Err(())
    }
}
fn main() {
    for line in io::stdin().lock().lines() {
        let mut case: Value = serde_json::from_str(&line.expect("stdin")).expect("vector JSON");
        let result = bridge(
            case["kind"].as_str().unwrap(),
            case["wire"].as_str().unwrap(),
            case["profile"].as_str(),
        );
        assert_eq!(
            result.is_ok(),
            case["valid"].as_bool().unwrap(),
            "{}",
            case["name"]
        );
        if let Ok(value) = &result {
            assert_eq!(value, &case["expected"], "{}", case["name"]);
        }
        case["bridge"] = result.unwrap_or(Value::Null);
        println!("{}", case);
    }
}
