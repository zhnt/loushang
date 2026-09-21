//! Cooperative stop wakes idle polling; in-flight IO keeps its deadline.
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;
#[derive(Clone, Default)]
pub struct ReadStop(Arc<(Mutex<bool>, Condvar)>);
impl ReadStop {
    pub fn request(&self) {
        let (flag, wake) = &*self.0;
        if let Ok(mut stopped) = flag.lock() {
            *stopped = true;
        }
        wake.notify_all();
    }
    pub fn requested(&self) -> Result<bool, ()> {
        self.0 .0.lock().map(|flag| *flag).map_err(|_| ())
    }
    pub fn wait(&self, interval: Duration) -> Result<bool, ()> {
        let (flag, wake) = &*self.0;
        let flag = flag.lock().map_err(|_| ())?;
        let (flag, _) = wake
            .wait_timeout_while(flag, interval, |value| !*value)
            .map_err(|_| ())?;
        Ok(*flag)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stop_is_sticky_and_wakes_a_waiter() {
        let stop = ReadStop::default();
        assert!(!stop.requested().unwrap());
        let waiter = stop.clone();
        let thread = std::thread::spawn(move || waiter.wait(Duration::from_secs(30)));
        stop.request();
        assert!(thread.join().unwrap().unwrap());
        assert!(stop.wait(Duration::from_secs(30)).unwrap());
    }
}
