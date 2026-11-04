//! Synthetic JSONL vectors only. Never output keys or original records.
#[allow(dead_code)]
#[path = "../../../../src-tauri/src/app_client/record_value.rs"]
mod record_value;
use serde::Deserialize;
use std::io::{self, BufRead};
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Case {
    payload: Vec<u8>,
    endpoint: String,
    profile: String,
}
fn main() {
    for line in io::stdin().lock().lines() {
        let result = line.map_err(|_| ()).and_then(|line| {
            let case: Case = serde_json::from_str(&line).map_err(|_| ())?;
            record_value::Record::decode(&case.payload)?.selected(&case.endpoint, &case.profile)
        });
        println!("{}", result.unwrap_or(serde_json::Value::Null));
    }
}
