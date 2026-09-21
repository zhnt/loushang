//! Owned blocking worker. Stop is nonblocking; join/drop belong off the UI thread.
use super::read_stop::ReadStop;
use std::thread::{self, JoinHandle};

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum WorkerFailure {
    Spawn,
    Operation,
    Panicked,
    Collected,
}

#[must_use = "retain the worker until its completion has been joined"]
pub(crate) struct ReadWorker<T> {
    stop: ReadStop,
    task: Option<JoinHandle<Result<T, ()>>>,
}
impl<T: Send + 'static> ReadWorker<T> {
    pub(crate) fn spawn(
        work: impl FnOnce(ReadStop) -> Result<T, ()> + Send + 'static,
    ) -> Result<Self, WorkerFailure> {
        let stop = ReadStop::default();
        let signal = stop.clone();
        let task = thread::Builder::new()
            .name("gui-read-worker".into())
            .spawn(move || work(signal))
            .map_err(|_| WorkerFailure::Spawn)?;
        Ok(Self {
            stop,
            task: Some(task),
        })
    }
}
impl<T> ReadWorker<T> {
    pub(crate) fn request_stop(&self) {
        self.stop.request();
    }

    /// Nonblocking completion observation; None means still running or collected.
    pub(crate) fn try_join(&mut self) -> Option<Result<T, WorkerFailure>> {
        if !self.task.as_ref()?.is_finished() {
            return None;
        }
        self.task.take().map(join)
    }

    /// Blocking: use from a native/background owner, never a UI event callback.
    pub(crate) fn wait(mut self) -> Result<T, WorkerFailure> {
        join(self.task.take().ok_or(WorkerFailure::Collected)?)
    }

    /// Cooperative stop and explicit cleanup result, with the same blocking rule.
    pub(crate) fn shutdown(self) -> Result<T, WorkerFailure> {
        self.request_stop();
        self.wait()
    }
}
fn join<T>(task: JoinHandle<Result<T, ()>>) -> Result<T, WorkerFailure> {
    task.join()
        .map_err(|_| WorkerFailure::Panicked)?
        .map_err(|_| WorkerFailure::Operation)
}
impl<T> Drop for ReadWorker<T> {
    fn drop(&mut self) {
        if let Some(task) = self.task.take() {
            self.stop.request();
            // Last-resort ownership settlement, not a successful-cleanup report.
            // The supplied operation must honor stop and bounded IO deadlines.
            let _ = join(task);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc,
    };
    use std::time::Duration;
    #[test]
    fn completion_and_failure_are_observed() {
        assert_eq!(ReadWorker::spawn(|_| Ok(42)).unwrap().wait(), Ok(42));
        assert_eq!(
            ReadWorker::spawn(|_| Err::<(), _>(())).unwrap().wait(),
            Err(WorkerFailure::Operation)
        );
        assert_eq!(
            ReadWorker::<()>::spawn(|_| panic!("test worker panic"))
                .unwrap()
                .wait(),
            Err(WorkerFailure::Panicked)
        );
    }
    #[test]
    fn stop_does_not_report_completion_before_cleanup() {
        let (entered, entering) = mpsc::channel();
        let (release, released) = mpsc::channel();
        let mut worker = ReadWorker::spawn(move |stop| {
            stop.wait(Duration::from_secs(5))?;
            entered.send(()).map_err(|_| ())?;
            released
                .recv_timeout(Duration::from_secs(5))
                .map_err(|_| ())?;
            Ok(())
        })
        .unwrap();
        worker.request_stop();
        entering.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(worker.try_join().is_none());
        release.send(()).unwrap();
        assert_eq!(worker.shutdown(), Ok(()));
    }
    #[test]
    fn drop_stops_and_joins() {
        let finished = Arc::new(AtomicBool::new(false));
        let flag = finished.clone();
        let worker = ReadWorker::spawn(move |stop| {
            if !stop.wait(Duration::from_secs(5))? {
                return Err(());
            }
            flag.store(true, Ordering::SeqCst);
            Ok(())
        })
        .unwrap();
        drop(worker);
        assert!(finished.load(Ordering::SeqCst));
    }
}
