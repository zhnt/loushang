//! One startup budget, then one fixed budget per sequential request/response.
use std::io;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

struct State {
    deadline: Instant,
    session: bool,
}
#[derive(Clone)]
pub struct RequestDeadline {
    state: Arc<Mutex<State>>,
    timeout: Duration,
}
impl RequestDeadline {
    pub fn new(timeout: Duration) -> Result<Self, ()> {
        if timeout.is_zero() {
            return Err(());
        }
        Ok(Self {
            state: Arc::new(Mutex::new(State {
                deadline: Instant::now().checked_add(timeout).ok_or(())?,
                session: false,
            })),
            timeout,
        })
    }
    pub fn remaining(&self) -> io::Result<Duration> {
        let state = self.state.lock().map_err(|_| expired())?;
        left(state.deadline, Instant::now()).ok_or_else(expired)
    }
    pub fn before_send(&self) -> Result<(), ()> {
        self.before_send_at(Instant::now())
    }
    fn before_send_at(&self, now: Instant) -> Result<(), ()> {
        let mut state = self.state.lock().map_err(|_| ())?;
        if state.session {
            state.deadline = now.checked_add(self.timeout).ok_or(())?;
        } else {
            left(state.deadline, now).ok_or(())?;
        }
        Ok(())
    }
    pub fn enter_session(&self) -> Result<(), ()> {
        let mut state = self.state.lock().map_err(|_| ())?;
        if state.session {
            return Err(());
        }
        left(state.deadline, Instant::now()).ok_or(())?;
        state.session = true;
        Ok(())
    }
}
fn left(deadline: Instant, now: Instant) -> Option<Duration> {
    deadline
        .checked_duration_since(now)
        .filter(|value| !value.is_zero())
}
fn expired() -> io::Error {
    io::Error::new(io::ErrorKind::TimedOut, "request deadline")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn startup_sends_do_not_renew_and_expiry_cannot_activate_session() {
        let clock = RequestDeadline::new(Duration::from_secs(1)).unwrap();
        let deadline = clock.state.lock().unwrap().deadline;
        clock
            .before_send_at(deadline - Duration::from_millis(1))
            .unwrap();
        assert_eq!(clock.state.lock().unwrap().deadline, deadline);
        assert!(clock.before_send_at(deadline).is_err());
        clock.state.lock().unwrap().deadline = Instant::now();
        assert!(clock.enter_session().is_err());
    }
    #[test]
    fn only_a_new_request_renews_a_session_deadline() {
        let clock = RequestDeadline::new(Duration::from_secs(1)).unwrap();
        clock.enter_session().unwrap();
        assert!(clock.enter_session().is_err());
        let start = Instant::now();
        clock.before_send_at(start).unwrap();
        let deadline = clock.state.lock().unwrap().deadline;
        assert_eq!(deadline, start + Duration::from_secs(1));
        for _ in 0..3 {
            let _ = clock.remaining();
        }
        assert_eq!(clock.state.lock().unwrap().deadline, deadline);
        clock
            .before_send_at(start + Duration::from_secs(2))
            .unwrap();
        assert_eq!(
            clock.state.lock().unwrap().deadline,
            start + Duration::from_secs(3)
        );
    }
}
