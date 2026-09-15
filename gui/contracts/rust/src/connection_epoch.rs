//! Local attempt fencing only: never a server controller generation or credential.
use std::sync::{Arc, Mutex};

#[derive(Default)]
struct State {
    last: u64,
    current: Option<u64>,
}

#[derive(Default)]
pub struct ConnectionOwner(Arc<Mutex<State>>);

#[derive(Clone)]
pub struct Fence {
    state: Arc<Mutex<State>>,
    epoch: u64,
}

pub struct Attempt(Fence);

impl ConnectionOwner {
    pub fn begin(&self) -> Result<Attempt, ()> {
        let mut state = self.0.lock().map_err(|_| ())?;
        // Fence the old attempt even if the counter is exhausted. Never wrap.
        state.current = None;
        state.last = state.last.checked_add(1).ok_or(())?;
        state.current = Some(state.last);
        Ok(Attempt(Fence {
            state: self.0.clone(),
            epoch: state.last,
        }))
    }
}

impl Fence {
    pub fn invalidate(&self) {
        if let Ok(mut state) = self.state.lock() {
            if state.current == Some(self.epoch) {
                state.current = None;
            }
        }
    }
}

impl Attempt {
    pub fn cancellation(&self) -> Fence {
        self.0.clone()
    }

    /// Run a short local state update atomically with the currency check.
    /// The callback must not perform IO, await, or reenter this owner.
    pub fn apply<T>(&self, update: impl FnOnce() -> Result<T, ()>) -> Result<T, ()> {
        let mut state = self.0.state.lock().map_err(|_| ())?;
        if state.current != Some(self.0.epoch) {
            return Err(());
        }
        let result = update();
        if result.is_err() {
            state.current = None;
        }
        result
    }
}

impl Drop for Attempt {
    fn drop(&mut self) {
        self.0.invalidate();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn replacement_rejects_old_results_and_old_cleanup_cannot_close_new_attempt() {
        let owner = ConnectionOwner::default();
        let old = owner.begin().unwrap();
        let cancel_old = old.cancellation();
        let new = owner.begin().unwrap();
        let mut installed = false;
        assert!(old
            .apply(|| {
                installed = true;
                Ok(())
            })
            .is_err());
        assert!(!installed);
        cancel_old.invalidate();
        drop(old);
        assert!(new.apply(|| Ok(())).is_ok());
    }
    #[test]
    fn cancellation_fences_a_delayed_worker_before_it_updates_state() {
        let owner = ConnectionOwner::default();
        let attempt = owner.begin().unwrap();
        let cancel = attempt.cancellation();
        let (send, receive) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            receive.recv().unwrap();
            attempt.apply(|| panic!("stale callback must not run"))
        });
        cancel.invalidate();
        send.send(()).unwrap();
        let result: Result<(), ()> = worker.join().unwrap();
        assert!(result.is_err());
    }
    #[test]
    fn errors_and_exhaustion_fail_closed() {
        let owner = ConnectionOwner::default();
        let attempt = owner.begin().unwrap();
        assert!(attempt.apply(|| Err::<(), _>(())).is_err());
        assert!(attempt.apply(|| Ok(())).is_err());
        owner.0.lock().unwrap().last = u64::MAX;
        assert!(owner.begin().is_err());
        assert_eq!(owner.0.lock().unwrap().current, None);
    }
}
