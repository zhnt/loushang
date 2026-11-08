//! Probes follow the same authoritative snapshot semantics as the desktop.
pub fn completed(sessions: &[serde_json::Value], prompt: &str) -> bool {
    sessions.iter().any(|session| {
        session["source"]["observation"]["status"] == "succeeded"
            && session["executions"]["active"].is_null()
            && session["source"]["source"]["records"]
                .as_array()
                .is_some_and(|records| records.iter().any(|record| record["text"] == prompt))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn authoritative_completion_does_not_require_replayed_content_events() {
        let snapshot = json!({
            "source": {"observation": {"status": "succeeded"},
                "source": {"records": [{"text": "new prompt"}]}},
            "executions": {"active": null}
        });
        assert!(completed(std::slice::from_ref(&snapshot), "new prompt"));
        assert!(!completed(
            std::slice::from_ref(&snapshot),
            "different prompt"
        ));
        let mut running = snapshot;
        running["source"]["observation"]["status"] = json!("running");
        assert!(!completed(&[running], "new prompt"));
    }
}
