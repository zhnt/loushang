//! Shared blocking authentication mechanics; the owning transport supplies deadlines.
use hmac::{Hmac, Mac};
use serde::Deserialize;
use sha2::Sha256;
use std::io::{Read, Write};
#[allow(dead_code)]
#[path = "record_value.rs"]
pub(crate) mod record_value;

const MESSAGE: usize = 1_048_576;
type Mac256 = Hmac<Sha256>;
type Result<T> = std::result::Result<T, ()>;

pub(crate) struct Frames<R, W> {
    reader: R,
    writer: W,
    limit: usize,
    closed: bool,
}
impl<R: Read, W: Write> Frames<R, W> {
    pub(crate) fn new(reader: R, writer: W) -> Self {
        Self {
            reader,
            writer,
            limit: 2048,
            closed: false,
        }
    }

    fn receive(&mut self) -> Result<Vec<u8>> {
        let result = (|| {
            if self.closed {
                return Err(());
            }
            let mut header = [0; 4];
            self.reader.read_exact(&mut header).map_err(|_| ())?;
            let len = u32::from_be_bytes(header) as usize;
            if len == 0 || len > self.limit {
                return Err(());
            }
            let mut body = vec![0; len];
            self.reader.read_exact(&mut body).map_err(|_| ())?;
            Ok(body)
        })();
        self.closed |= result.is_err();
        result
    }
    fn send(&mut self, body: &[u8]) -> Result<()> {
        let result = (|| {
            if self.closed || body.is_empty() || body.len() > self.limit {
                return Err(());
            }
            self.writer
                .write_all(&(body.len() as u32).to_be_bytes())
                .map_err(|_| ())?;
            self.writer.write_all(body).map_err(|_| ())?;
            self.writer.flush().map_err(|_| ())
        })();
        self.closed |= result.is_err();
        result
    }
}
fn mac(key: &[u8], parts: &[&[u8]]) -> Mac256 {
    let mut value = Mac256::new_from_slice(key).expect("HMAC permits any key length");
    for part in parts {
        value.update(part);
    }
    value
}
fn proof(key: &[u8], role: &[u8], transcript: &[u8]) -> [u8; 32] {
    mac(key, &[role, b"\0", transcript])
        .finalize()
        .into_bytes()
        .into()
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
fn unhex(value: &str) -> Result<[u8; 32]> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(());
    }
    let mut bytes = [0; 32];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16).map_err(|_| ())?;
    }
    Ok(bytes)
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Challenge {
    profile: String,
    protocol: String,
    instance: String,
    server_nonce: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ServerProof {
    proof: String,
}

pub(crate) struct Channel<R, W> {
    frames: Frames<R, W>,
    send_key: [u8; 32],
    receive_key: [u8; 32],
    send_sequence: Option<u64>,
    receive_sequence: Option<u64>,
}
impl<R: Read, W: Write> Channel<R, W> {
    pub(crate) fn authenticate(
        mut frames: Frames<R, W>,
        record: &record_value::Record,
    ) -> Result<Self> {
        let challenge: Challenge = serde_json::from_slice(&frames.receive()?).map_err(|_| ())?;
        if challenge.profile != "local-detachable/v1"
            || challenge.protocol != "loushang.app/v1"
            || challenge.instance != record.instance
        {
            return Err(());
        }
        let server_nonce = unhex(&challenge.server_nonce)?;
        let mut client_nonce = [0; 32];
        getrandom::getrandom(&mut client_nonce).map_err(|_| ())?;
        let key = record.key()?;
        let digest = record.digest()?;
        let mut transcript = b"local-detachable/v1\0loushang.app/v1\0".to_vec();
        transcript.extend(&digest);
        transcript.extend(server_nonce);
        transcript.extend(client_nonce);
        let response = serde_json::json!({"client_nonce": hex(&client_nonce), "proof": hex(&proof(&key, b"client", &transcript))});
        frames.send(&serde_json::to_vec(&response).map_err(|_| ())?)?;
        let server: ServerProof = serde_json::from_slice(&frames.receive()?).map_err(|_| ())?;
        mac(&key, &[b"server", b"\0", &transcript])
            .verify_slice(&unhex(&server.proof)?)
            .map_err(|_| ())?;
        frames.limit = MESSAGE + 40;
        Ok(Self {
            frames,
            send_key: proof(&key, b"c2s", &transcript),
            receive_key: proof(&key, b"s2c", &transcript),
            send_sequence: Some(1),
            receive_sequence: Some(1),
        })
    }
    pub(crate) fn receive(&mut self) -> Result<Vec<u8>> {
        let result = (|| {
            let envelope = self.frames.receive()?;
            let expected = self.receive_sequence.ok_or(())?;
            if envelope.len() <= 40 {
                return Err(());
            }
            let sequence: [u8; 8] = envelope[..8].try_into().map_err(|_| ())?;
            if u64::from_be_bytes(sequence) != expected {
                return Err(());
            }
            mac(&self.receive_key, &[&sequence, &envelope[40..]])
                .verify_slice(&envelope[8..40])
                .map_err(|_| ())?;
            self.receive_sequence = expected.checked_add(1);
            Ok(envelope[40..].to_vec())
        })();
        self.frames.closed |= result.is_err();
        result
    }
    pub(crate) fn send(&mut self, payload: &[u8]) -> Result<()> {
        let result = (|| {
            if payload.is_empty() || payload.len() > MESSAGE {
                return Err(());
            }
            let sequence = self.send_sequence.ok_or(())?;
            let bytes = sequence.to_be_bytes();
            let tag = mac(&self.send_key, &[&bytes, payload])
                .finalize()
                .into_bytes();
            let mut envelope = bytes.to_vec();
            envelope.extend(tag);
            envelope.extend(payload);
            self.send_sequence = sequence.checked_add(1);
            self.frames.send(&envelope)
        })();
        self.frames.closed |= result.is_err();
        result
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    #[test]
    fn framing_fences_truncation_and_bounds() {
        for bytes in [
            vec![],
            vec![0],
            vec![0, 0, 0, 0],
            vec![0, 0, 8, 1],
            vec![0, 0, 0, 2, 1],
        ] {
            let mut frames = Frames {
                reader: Cursor::new(bytes),
                writer: Vec::new(),
                limit: 2048,
                closed: false,
            };
            assert!(frames.receive().is_err());
            assert!(frames.closed);
            assert!(frames.send(b"late").is_err());
        }
    }
    #[test]
    fn framing_reads_adjacent_messages_and_writes_big_endian() {
        let mut frames = Frames {
            reader: Cursor::new(vec![0, 0, 0, 1, 65, 0, 0, 0, 1, 66]),
            writer: Vec::new(),
            limit: 2048,
            closed: false,
        };
        assert_eq!(frames.receive(), Ok(vec![65]));
        assert_eq!(frames.receive(), Ok(vec![66]));
        assert_eq!(frames.send(b"ok"), Ok(()));
        assert_eq!(frames.writer, vec![0, 0, 0, 2, 111, 107]);
    }
    #[test]
    fn sequence_exhaustion_and_bad_tag_fence_channel() {
        let mut channel = Channel {
            frames: Frames {
                reader: Cursor::new(vec![]),
                writer: Vec::new(),
                limit: MESSAGE + 40,
                closed: false,
            },
            send_key: [1; 32],
            receive_key: [2; 32],
            send_sequence: Some(u64::MAX),
            receive_sequence: Some(1),
        };
        assert!(channel.send(b"last").is_ok());
        assert!(channel.send(b"overflow").is_err());
        assert!(channel.frames.closed);
        channel.frames.closed = false;
        channel.frames.reader = Cursor::new([vec![0, 0, 0, 41], vec![0; 41]].concat());
        assert!(channel.receive().is_err());
        assert!(channel.frames.closed);
    }
}
