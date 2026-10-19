//! The Private folder: an encrypted video vault inside the library
//! (`<library>/vault/`, see
//! `docs/superpowers/specs/2026-10-19-private-video-vault-design.md`).
//!
//! A random 256-bit data key encrypts everything (AES-256-GCM). It is stored
//! wrapped under a key derived from the password with Argon2id, so a password
//! change only re-wraps it. Videos are split into 64 KiB chunks, each sealed
//! with nonce = file prefix ‖ chunk index and the file header as associated
//! data, so a range of a video can be decrypted without reading the rest and
//! reordered, truncated or edited chunks fail. Titles live only in the
//! encrypted index; file names are random.

use std::fs::{self, File};
use std::io::{self, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use aes_gcm::aead::rand_core::RngCore;
use aes_gcm::aead::{Aead, AeadCore, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Key as GcmKey, Nonce};
use argon2::{Algorithm, Argon2, Params, Version};
use base64::Engine;
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

const MAGIC: &[u8; 8] = b"QTMVAULT";
const FORMAT: u8 = 1;
/// Plaintext bytes per chunk.
pub const CHUNK: usize = 64 * 1024;
const TAG: usize = 16;
/// magic(8) format(1) reserved(3) nonce prefix(8) chunk size(4) length(8).
const HEADER: usize = 32;
/// Shortest password accepted.
pub const MIN_PASSWORD: usize = 8;

/// Serialises every index change in the process. Moves run in background
/// threads for minutes; without this, two of them (or a delete during one)
/// would each save their own copy of the index and drop the other's item.
static INDEX_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn index_lock() -> std::sync::MutexGuard<'static, ()> {
    INDEX_LOCK
        .lock()
        .unwrap_or_else(|poison| poison.into_inner())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct KdfParams {
    pub memory_kib: u32,
    pub passes: u32,
    pub lanes: u32,
}

/// OWASP's Argon2id recommendation for interactive logins (~0.5 s here).
pub const DEFAULT_KDF: KdfParams = KdfParams {
    memory_kib: 64 * 1024,
    passes: 3,
    lanes: 1,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultError {
    Missing,
    Exists,
    WrongPassword,
    WeakPassword,
    Corrupt,
    NotFound,
    Storage,
}

impl VaultError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Missing => "vault_missing",
            Self::Exists => "vault_exists",
            Self::WrongPassword => "vault_wrong_password",
            Self::WeakPassword => "vault_weak_password",
            Self::Corrupt => "vault_corrupt",
            Self::NotFound => "not_found",
            Self::Storage => "storage_unavailable",
        }
    }
}

impl From<io::Error> for VaultError {
    fn from(error: io::Error) -> Self {
        if error.kind() == io::ErrorKind::NotFound {
            Self::NotFound
        } else {
            Self::Storage
        }
    }
}

/// The unlocked data key. Zeroed when the last copy is dropped.
#[derive(Clone)]
pub struct VaultKey(Zeroizing<[u8; 32]>);

impl VaultKey {
    fn cipher(&self) -> Aes256Gcm {
        Aes256Gcm::new(GcmKey::<Aes256Gcm>::from_slice(self.0.as_slice()))
    }
}

fn derive(password: &str, salt: &[u8], params: KdfParams) -> Result<VaultKey, VaultError> {
    let params = Params::new(params.memory_kib, params.passes, params.lanes, Some(32))
        .map_err(|_| VaultError::Corrupt)?;
    let mut out = Zeroizing::new([0u8; 32]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into(password.as_bytes(), salt, out.as_mut_slice())
        .map_err(|_| VaultError::Corrupt)?;
    Ok(VaultKey(out))
}

/// `nonce ‖ ciphertext+tag` of `plain` under `key`.
fn seal(key: &VaultKey, plain: &[u8]) -> Vec<u8> {
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    let mut out = nonce.to_vec();
    out.extend(
        key.cipher()
            .encrypt(&nonce, plain)
            .expect("AES-GCM encryption of an in-memory buffer"),
    );
    out
}

fn open(key: &VaultKey, sealed: &[u8]) -> Result<Zeroizing<Vec<u8>>, VaultError> {
    if sealed.len() < 12 + TAG {
        return Err(VaultError::Corrupt);
    }
    let (nonce, body) = sealed.split_at(12);
    key.cipher()
        .decrypt(Nonce::from_slice(nonce), body)
        .map(Zeroizing::new)
        .map_err(|_| VaultError::WrongPassword)
}

fn b64() -> base64::engine::GeneralPurpose {
    base64::engine::general_purpose::STANDARD
}

#[derive(Serialize, Deserialize)]
struct KeyFile {
    version: u32,
    kdf: KdfParams,
    salt: String,
    wrapped_key: String,
}

/// One video in the vault (as stored in the encrypted index).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VaultItem {
    /// 32 hex digits: `vault/<id>.qv` on disk.
    pub id: String,
    pub title: String,
    /// The original file name, used when restoring it to the library.
    pub original_name: String,
    /// Extension of the stored (playable) file.
    pub extension: String,
    pub size_bytes: u64,
    pub duration_seconds: Option<f64>,
    pub added_at: f64,
    pub has_cover: bool,
    /// Converted to a playable format when it was added.
    #[serde(default)]
    pub converted: bool,
}

#[derive(Default, Serialize, Deserialize)]
struct Index {
    version: u32,
    items: Vec<VaultItem>,
}

/// What a caller knows about a video it moves into the vault.
pub struct NewItem<'a> {
    /// The file to encrypt (the original, or a playable copy of it).
    pub source: &'a Path,
    pub cover: Option<&'a Path>,
    pub title: String,
    pub original_name: String,
    pub duration_seconds: Option<f64>,
    pub converted: bool,
}

fn new_id() -> String {
    let mut bytes = [0u8; 16];
    OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Whether `id` is a vault file id (never a path).
pub fn is_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Whole seconds: they survive the JSON round trip exactly (serde_json does
/// not promise exact round trips for fractional floats).
fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |duration| duration.as_secs() as f64)
}

fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, bytes)?;
    fs::rename(&temporary, path)
}

// --- Chunked file encryption ----------------------------------------------------

fn header(prefix: &[u8; 8], length: u64) -> [u8; HEADER] {
    let mut header = [0u8; HEADER];
    header[..8].copy_from_slice(MAGIC);
    header[8] = FORMAT;
    header[12..20].copy_from_slice(prefix);
    header[20..24].copy_from_slice(&(CHUNK as u32).to_le_bytes());
    header[24..32].copy_from_slice(&length.to_le_bytes());
    header
}

fn chunk_nonce(prefix: &[u8; 8], index: u64) -> [u8; 12] {
    let mut nonce = [0u8; 12];
    nonce[..8].copy_from_slice(prefix);
    nonce[8..].copy_from_slice(&(index as u32).to_be_bytes());
    nonce
}

/// Encrypts `source` into `destination`, reporting `(done, total)` bytes.
/// Returns the plaintext length. A partial file is removed on failure.
pub fn encrypt_file(
    key: &VaultKey,
    source: &Path,
    destination: &Path,
    mut progress: impl FnMut(u64, u64),
) -> Result<u64, VaultError> {
    let result = (|| {
        let mut input = File::open(source)?;
        let length = input.metadata()?.len();
        if length.div_ceil(CHUNK as u64) > u64::from(u32::MAX) {
            return Err(VaultError::Storage);
        }
        let mut prefix = [0u8; 8];
        OsRng.fill_bytes(&mut prefix);
        let header = header(&prefix, length);
        let part = destination.with_extension("part");
        let mut output = io::BufWriter::new(File::create(&part)?);
        output.write_all(&header)?;
        let cipher = key.cipher();
        let mut buffer = Zeroizing::new(vec![0u8; CHUNK]);
        let mut done = 0u64;
        let mut index = 0u64;
        while done < length {
            let take = (length - done).min(CHUNK as u64) as usize;
            input.read_exact(&mut buffer[..take])?;
            let sealed = cipher
                .encrypt(
                    Nonce::from_slice(&chunk_nonce(&prefix, index)),
                    Payload {
                        msg: &buffer[..take],
                        aad: &header,
                    },
                )
                .map_err(|_| VaultError::Storage)?;
            output.write_all(&sealed)?;
            done += take as u64;
            index += 1;
            progress(done, length);
        }
        output.flush()?;
        output.get_ref().sync_all()?;
        drop(output);
        fs::rename(&part, destination)?;
        Ok(length)
    })();
    if result.is_err() {
        let _ = fs::remove_file(destination.with_extension("part"));
    }
    result
}

/// Random-access decryption of one vault file.
pub struct VaultReader {
    file: File,
    cipher: Aes256Gcm,
    header: [u8; HEADER],
    prefix: [u8; 8],
    length: u64,
}

impl VaultReader {
    pub fn open(key: &VaultKey, path: &Path) -> Result<Self, VaultError> {
        let mut file = File::open(path)?;
        let mut header = [0u8; HEADER];
        file.read_exact(&mut header)
            .map_err(|_| VaultError::Corrupt)?;
        if &header[..8] != MAGIC || header[8] != FORMAT {
            return Err(VaultError::Corrupt);
        }
        if u32::from_le_bytes(header[20..24].try_into().unwrap()) as usize != CHUNK {
            return Err(VaultError::Corrupt);
        }
        let mut prefix = [0u8; 8];
        prefix.copy_from_slice(&header[12..20]);
        let length = u64::from_le_bytes(header[24..32].try_into().unwrap());
        Ok(Self {
            file,
            cipher: key.cipher(),
            header,
            prefix,
            length,
        })
    }

    /// Plaintext length of the video.
    pub fn len(&self) -> u64 {
        self.length
    }

    pub fn is_empty(&self) -> bool {
        self.length == 0
    }

    /// Plaintext bytes `start..end` (clamped to the length).
    pub fn read_range(&mut self, start: u64, end: u64) -> Result<Vec<u8>, VaultError> {
        let end = end.min(self.length);
        if start >= end {
            return Ok(Vec::new());
        }
        let mut out = Vec::with_capacity((end - start) as usize);
        let first = start / CHUNK as u64;
        let last = (end - 1) / CHUNK as u64;
        let mut sealed = vec![0u8; CHUNK + TAG];
        for index in first..=last {
            let chunk_start = index * CHUNK as u64;
            let plain_len = (self.length - chunk_start).min(CHUNK as u64) as usize;
            let offset = HEADER as u64 + index * (CHUNK + TAG) as u64;
            self.file.seek(SeekFrom::Start(offset))?;
            self.file
                .read_exact(&mut sealed[..plain_len + TAG])
                .map_err(|_| VaultError::Corrupt)?;
            let plain = Zeroizing::new(
                self.cipher
                    .decrypt(
                        Nonce::from_slice(&chunk_nonce(&self.prefix, index)),
                        Payload {
                            msg: &sealed[..plain_len + TAG],
                            aad: &self.header,
                        },
                    )
                    .map_err(|_| VaultError::Corrupt)?,
            );
            let from = start.saturating_sub(chunk_start) as usize;
            let to = ((end - chunk_start) as usize).min(plain.len());
            out.extend_from_slice(&plain[from..to]);
        }
        Ok(out)
    }

    /// Decrypts the whole file into `destination`.
    pub fn decrypt_to(&mut self, destination: &Path) -> Result<(), VaultError> {
        let part = destination.with_extension("part");
        let result = (|| {
            let mut output = io::BufWriter::new(File::create(&part)?);
            let mut done = 0;
            while done < self.length {
                let next = (done + 16 * CHUNK as u64).min(self.length);
                output.write_all(&self.read_range(done, next)?)?;
                done = next;
            }
            output.flush()?;
            drop(output);
            fs::rename(&part, destination)?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&part);
        }
        result
    }
}

// --- The vault --------------------------------------------------------------------

pub struct Vault {
    dir: PathBuf,
}

impl Vault {
    /// The vault of the library at `root`.
    pub fn of_library(root: &Path) -> Self {
        Self {
            dir: root.join("vault"),
        }
    }

    fn key_file(&self) -> PathBuf {
        self.dir.join("vault.json")
    }

    fn index_file(&self) -> PathBuf {
        self.dir.join("index.qv")
    }

    pub fn video_path(&self, id: &str) -> PathBuf {
        self.dir.join(format!("{id}.qv"))
    }

    fn cover_path(&self, id: &str) -> PathBuf {
        self.dir.join(format!("{id}.cover"))
    }

    pub fn exists(&self) -> bool {
        self.key_file().is_file()
    }

    /// Creates the vault with `password`; returns the unlocked key.
    pub fn create(&self, password: &str, kdf: KdfParams) -> Result<VaultKey, VaultError> {
        if self.exists() {
            return Err(VaultError::Exists);
        }
        if password.chars().count() < MIN_PASSWORD {
            return Err(VaultError::WeakPassword);
        }
        fs::create_dir_all(&self.dir)?;
        let mut data = Zeroizing::new([0u8; 32]);
        OsRng.fill_bytes(data.as_mut_slice());
        let key = VaultKey(data);
        self.wrap(&key, password, kdf)?;
        self.save_index(
            &key,
            &Index {
                version: 1,
                items: Vec::new(),
            },
        )?;
        Ok(key)
    }

    fn wrap(&self, key: &VaultKey, password: &str, kdf: KdfParams) -> Result<(), VaultError> {
        let mut salt = [0u8; 16];
        OsRng.fill_bytes(&mut salt);
        let wrapping = derive(password, &salt, kdf)?;
        let file = KeyFile {
            version: 1,
            kdf,
            salt: b64().encode(salt),
            wrapped_key: b64().encode(seal(&wrapping, key.0.as_slice())),
        };
        let bytes = serde_json::to_vec_pretty(&file).map_err(|_| VaultError::Storage)?;
        write_atomic(&self.key_file(), &bytes)?;
        Ok(())
    }

    /// The data key for `password` (`WrongPassword` otherwise).
    pub fn unlock(&self, password: &str) -> Result<VaultKey, VaultError> {
        let bytes = fs::read(self.key_file()).map_err(|_| VaultError::Missing)?;
        let file: KeyFile = serde_json::from_slice(&bytes).map_err(|_| VaultError::Corrupt)?;
        let salt = b64().decode(&file.salt).map_err(|_| VaultError::Corrupt)?;
        let wrapped = b64()
            .decode(&file.wrapped_key)
            .map_err(|_| VaultError::Corrupt)?;
        let wrapping = derive(password, &salt, file.kdf)?;
        let plain = open(&wrapping, &wrapped)?;
        let data: [u8; 32] = plain
            .as_slice()
            .try_into()
            .map_err(|_| VaultError::Corrupt)?;
        Ok(VaultKey(Zeroizing::new(data)))
    }

    pub fn change_password(&self, old: &str, new: &str, kdf: KdfParams) -> Result<(), VaultError> {
        if new.chars().count() < MIN_PASSWORD {
            return Err(VaultError::WeakPassword);
        }
        let key = self.unlock(old)?;
        self.wrap(&key, new, kdf)
    }

    fn load_index(&self, key: &VaultKey) -> Result<Index, VaultError> {
        let sealed = fs::read(self.index_file())?;
        let plain = open(key, &sealed).map_err(|_| VaultError::Corrupt)?;
        serde_json::from_slice(&plain).map_err(|_| VaultError::Corrupt)
    }

    fn save_index(&self, key: &VaultKey, index: &Index) -> Result<(), VaultError> {
        let plain = Zeroizing::new(serde_json::to_vec(index).map_err(|_| VaultError::Storage)?);
        write_atomic(&self.index_file(), &seal(key, &plain))?;
        Ok(())
    }

    /// Items, newest first.
    pub fn items(&self, key: &VaultKey) -> Result<Vec<VaultItem>, VaultError> {
        let mut items = self.load_index(key)?.items;
        items.sort_by(|a, b| b.added_at.total_cmp(&a.added_at));
        Ok(items)
    }

    pub fn item(&self, key: &VaultKey, id: &str) -> Result<VaultItem, VaultError> {
        self.load_index(key)?
            .items
            .into_iter()
            .find(|item| item.id == id)
            .ok_or(VaultError::NotFound)
    }

    /// Encrypts a video (and its cover) into the vault and records it. The
    /// caller removes the originals only after this succeeds.
    pub fn add(
        &self,
        key: &VaultKey,
        item: NewItem<'_>,
        progress: impl FnMut(u64, u64),
    ) -> Result<VaultItem, VaultError> {
        fs::create_dir_all(&self.dir)?;
        // Fail early on a locked or damaged vault, before encrypting anything.
        self.load_index(key)?;
        let id = new_id();
        let video = self.video_path(&id);
        let size = encrypt_file(key, item.source, &video, progress)?;
        let has_cover = match item.cover {
            Some(cover) => match encrypt_file(key, cover, &self.cover_path(&id), |_, _| {}) {
                Ok(_) => true,
                Err(_) => false,
            },
            None => false,
        };
        let extension = item
            .source
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("mp4")
            .to_ascii_lowercase();
        let entry = VaultItem {
            id: id.clone(),
            title: item.title,
            original_name: item.original_name,
            extension,
            size_bytes: size,
            duration_seconds: item.duration_seconds,
            added_at: now(),
            has_cover,
            converted: item.converted,
        };
        // Record it against the index as it is now, not as it was before the
        // (long) encryption.
        let _guard = index_lock();
        let saved = self.load_index(key).and_then(|mut index| {
            index.items.push(entry.clone());
            self.save_index(key, &index)
        });
        if let Err(error) = saved {
            let _ = fs::remove_file(&video);
            let _ = fs::remove_file(self.cover_path(&id));
            return Err(error);
        }
        Ok(entry)
    }

    pub fn reader(&self, key: &VaultKey, id: &str) -> Result<VaultReader, VaultError> {
        if !is_id(id) {
            return Err(VaultError::NotFound);
        }
        VaultReader::open(key, &self.video_path(id))
    }

    pub fn cover(&self, key: &VaultKey, id: &str) -> Result<Option<Vec<u8>>, VaultError> {
        if !is_id(id) || !self.cover_path(id).is_file() {
            return Ok(None);
        }
        let mut reader = VaultReader::open(key, &self.cover_path(id))?;
        let length = reader.len();
        reader.read_range(0, length).map(Some)
    }

    /// Decrypts an item back into the library (`video/`, `artwork/`) under a
    /// free name and removes it from the vault. Returns the new `video/…` path.
    pub fn restore(&self, key: &VaultKey, id: &str, library: &Path) -> Result<String, VaultError> {
        // Whole restore under the lock: a second click must not decrypt the
        // same item again.
        let _guard = index_lock();
        let item = self.item(key, id)?;
        let stem = Path::new(&item.original_name)
            .file_stem()
            .and_then(|value| value.to_str())
            .map(str::to_owned)
            .unwrap_or_else(|| item.title.clone());
        let taken = |stem: &str| {
            ["video", "artwork"].iter().any(|folder| {
                fs::read_dir(library.join(folder)).is_ok_and(|entries| {
                    entries.flatten().any(|entry| {
                        Path::new(&entry.file_name())
                            .file_stem()
                            .and_then(|value| value.to_str())
                            .is_some_and(|existing| existing.eq_ignore_ascii_case(stem))
                    })
                })
            })
        };
        let free = std::iter::once(stem.clone())
            .chain((2..10_000).map(|n| format!("{stem} ({n})")))
            .find(|candidate| !taken(candidate))
            .ok_or(VaultError::Storage)?;
        fs::create_dir_all(library.join("video"))?;
        let relative = format!("video/{free}.{}", item.extension);
        self.reader(key, id)?.decrypt_to(&library.join(&relative))?;
        if let Ok(Some(cover)) = self.cover(key, id) {
            let _ = fs::create_dir_all(library.join("artwork"));
            let _ = fs::write(library.join("artwork").join(format!("{free}.jpg")), cover);
        }
        self.remove_item(key, id)?;
        Ok(relative)
    }

    /// Removes an item from the vault for good.
    pub fn delete(&self, key: &VaultKey, id: &str) -> Result<(), VaultError> {
        let _guard = index_lock();
        self.remove_item(key, id)
    }

    /// `delete` without taking the lock (the caller holds it).
    fn remove_item(&self, key: &VaultKey, id: &str) -> Result<(), VaultError> {
        let mut index = self.load_index(key)?;
        let before = index.items.len();
        index.items.retain(|item| item.id != id);
        if index.items.len() == before {
            return Err(VaultError::NotFound);
        }
        self.save_index(key, &index)?;
        let _ = fs::remove_file(self.video_path(id));
        let _ = fs::remove_file(self.cover_path(id));
        Ok(())
    }
}
