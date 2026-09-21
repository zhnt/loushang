//! Desktop ownership only; no AppHost stop, reconnect or transport semantics.
use crate::read_stop::ReadStop;
use crate::read_worker::{ReadWorker, WorkerFailure};
use std::sync::Mutex;

#[derive(Default)]
pub(crate) struct ConnectionLifecycle(Mutex<Phase>);

#[derive(Default)]
enum Phase {
    #[default]
    Idle,
    Reading(ReadWorker<()>),
    Closing,
    Closed(Result<(), WorkerFailure>),
}

pub(crate) enum ExitAction {
    Ready,
    Pending,
    Join(ReadWorker<()>),
}

impl ConnectionLifecycle {
    // Kept native-only until admission and snapshot publication are wired.
    pub(crate) fn start(
        &self,
        work: impl FnOnce(ReadStop) -> Result<(), ()> + Send + 'static,
    ) -> Result<(), ()> {
        let mut phase = self.0.lock().map_err(|_| ())?;
        if !matches!(*phase, Phase::Idle) {
            return Err(());
        }
        *phase = Phase::Reading(ReadWorker::spawn(work).map_err(|_| ())?);
        Ok(())
    }

    /// No joins and no user callbacks under this lock. Repeated exit is idempotent.
    pub(crate) fn begin_exit(&self) -> ExitAction {
        let mut phase = self.0.lock().unwrap_or_else(|error| error.into_inner());
        match &*phase {
            Phase::Closing => return ExitAction::Pending,
            Phase::Closed(_) => return ExitAction::Ready,
            Phase::Idle => {
                *phase = Phase::Closed(Ok(()));
                return ExitAction::Ready;
            }
            Phase::Reading(worker) => worker.request_stop(),
        }
        match std::mem::replace(&mut *phase, Phase::Closing) {
            Phase::Reading(worker) => ExitAction::Join(worker),
            _ => unreachable!(),
        }
    }

    /// Called only by the background join owner; result survives until exit.
    pub(crate) fn finish_exit(&self, outcome: Result<(), WorkerFailure>) {
        let mut phase = self.0.lock().unwrap_or_else(|error| error.into_inner());
        if matches!(*phase, Phase::Closing) {
            *phase = Phase::Closed(outcome);
        }
    }

    pub(crate) fn cleanup_failed(&self) -> bool {
        let phase = self.0.lock().unwrap_or_else(|error| error.into_inner());
        matches!(*phase, Phase::Closed(Err(_)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;
    use std::time::Duration;

    #[test]
    fn idle_exit_is_immediate_and_rejects_late_start() {
        let owner = ConnectionLifecycle::default();
        assert!(matches!(owner.begin_exit(), ExitAction::Ready));
        assert!(owner.start(|_| Ok(())).is_err());
        assert!(!owner.cleanup_failed());
    }

    #[test]
    fn exit_waits_for_cleanup_without_holding_the_state_lock() {
        let owner = ConnectionLifecycle::default();
        let (release, released) = mpsc::channel();
        owner
            .start(move |stop| {
                if !stop.wait(Duration::from_secs(5))? {
                    return Err(());
                }
                released
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(|_| ())
            })
            .unwrap();
        assert!(owner.start(|_| Ok(())).is_err());
        let ExitAction::Join(worker) = owner.begin_exit() else {
            panic!("missing worker");
        };
        // Callback can return while cleanup is still blocked.
        assert!(matches!(owner.begin_exit(), ExitAction::Pending));
        assert!(owner.start(|_| Ok(())).is_err());
        release.send(()).unwrap();
        owner.finish_exit(worker.wait());
        assert!(matches!(owner.begin_exit(), ExitAction::Ready));
        assert!(!owner.cleanup_failed());
    }

    #[test]
    fn cleanup_failure_is_retained_and_not_overwritten() {
        let owner = ConnectionLifecycle::default();
        owner.start(|_| Err(())).unwrap();
        let ExitAction::Join(worker) = owner.begin_exit() else {
            panic!("missing worker");
        };
        owner.finish_exit(worker.wait());
        assert!(matches!(owner.begin_exit(), ExitAction::Ready));
        owner.finish_exit(Ok(()));
        assert!(owner.cleanup_failed());
    }
}
