use std::fs;
use std::path::Path;

use qtmedia_app::vault::{
    encrypt_file, is_id, KdfParams, NewItem, Vault, VaultError, VaultReader, CHUNK,
};

/// Light Argon2 settings so tests stay fast (the app uses DEFAULT_KDF).
const FAST: KdfParams = KdfParams {
    memory_kib: 1024,
    passes: 1,
    lanes: 1,
};

fn library() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    for folder in ["audio", "video", "artwork", "temp"] {
        fs::create_dir_all(dir.path().join(folder)).unwrap();
    }
    dir
}

fn pattern(len: usize) -> Vec<u8> {
    (0..len).map(|i| (i * 31 % 251) as u8).collect()
}

fn add(
    vault: &Vault,
    key: &qtmedia_app::vault::VaultKey,
    source: &Path,
    cover: Option<&Path>,
    title: &str,
) -> qtmedia_app::vault::VaultItem {
    vault
        .add(
            key,
            NewItem {
                source,
                cover,
                title: title.into(),
                original_name: source.file_name().unwrap().to_string_lossy().into_owned(),
                duration_seconds: Some(12.0),
                converted: false,
            },
            |_, _| {},
        )
        .unwrap()
}

#[test]
fn passwords_create_unlock_and_change() {
    let dir = library();
    let vault = Vault::of_library(dir.path());
    assert!(!vault.exists());
    assert_eq!(
        vault.create("short", FAST).err(),
        Some(VaultError::WeakPassword)
    );
    vault.create("correct horse", FAST).unwrap();
    assert!(vault.exists());
    assert_eq!(
        vault.create("correct horse", FAST).err(),
        Some(VaultError::Exists)
    );
    assert_eq!(
        vault.unlock("wrong password").err(),
        Some(VaultError::WrongPassword)
    );
    let key = vault.unlock("correct horse").unwrap();
    assert!(vault.items(&key).unwrap().is_empty());

    // A new password re-wraps the same key: existing items stay readable.
    let source = dir.path().join("video/Film.mp4");
    fs::write(&source, pattern(1000)).unwrap();
    let item = add(&vault, &key, &source, None, "Film");
    assert_eq!(
        vault.change_password("wrong", "new password", FAST).err(),
        Some(VaultError::WrongPassword)
    );
    vault
        .change_password("correct horse", "new password", FAST)
        .unwrap();
    assert_eq!(
        vault.unlock("correct horse").err(),
        Some(VaultError::WrongPassword)
    );
    let again = vault.unlock("new password").unwrap();
    assert_eq!(vault.items(&again).unwrap(), vec![item]);
}

#[test]
fn nothing_readable_is_left_on_disk() {
    let dir = library();
    let vault = Vault::of_library(dir.path());
    let key = vault.create("correct horse", FAST).unwrap();
    let source = dir.path().join("video/My Secret Holiday.mp4");
    let plain = b"PLAINTEXT-MARKER ".repeat(10_000);
    fs::write(&source, &plain).unwrap();
    let item = add(&vault, &key, &source, None, "My Secret Holiday");

    assert!(is_id(&item.id));
    for entry in fs::read_dir(dir.path().join("vault")).unwrap().flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        assert!(!name.contains("Secret"), "{name}");
        let bytes = fs::read(entry.path()).unwrap();
        let text = String::from_utf8_lossy(&bytes);
        assert!(
            !text.contains("Secret") && !text.contains("PLAINTEXT-MARKER"),
            "{name}"
        );
    }
}

#[test]
fn any_range_decrypts_exactly() {
    let dir = library();
    let vault = Vault::of_library(dir.path());
    let key = vault.create("correct horse", FAST).unwrap();
    let data = pattern(3 * CHUNK + 777);
    let source = dir.path().join("video/Clip.mp4");
    fs::write(&source, &data).unwrap();
    let item = add(&vault, &key, &source, None, "Clip");

    let mut reader = vault.reader(&key, &item.id).unwrap();
    assert_eq!(reader.len(), data.len() as u64);
    for (start, end) in [
        (0, 10),
        (CHUNK - 5, CHUNK + 5),
        (100, 3 * CHUNK + 777),
        (2 * CHUNK, 2 * CHUNK),
        (3 * CHUNK + 700, 9 * CHUNK),
    ] {
        let got = reader.read_range(start as u64, end as u64).unwrap();
        let end = end.min(data.len());
        assert_eq!(got, data[start.min(end)..end], "{start}..{end}");
    }
}

#[test]
fn tampering_truncation_and_swapped_chunks_are_refused() {
    let dir = library();
    let vault = Vault::of_library(dir.path());
    let key = vault.create("correct horse", FAST).unwrap();
    let source = dir.path().join("video/Clip.mp4");
    fs::write(&source, pattern(2 * CHUNK + 10)).unwrap();
    let encrypted = dir.path().join("temp/clip.qv");
    encrypt_file(&key, &source, &encrypted, |_, _| {}).unwrap();
    let original = fs::read(&encrypted).unwrap();

    let check = |bytes: Vec<u8>| {
        let path = dir.path().join("temp/broken.qv");
        fs::write(&path, bytes).unwrap();
        VaultReader::open(&key, &path).and_then(|mut reader| {
            let len = reader.len();
            reader.read_range(0, len)
        })
    };
    let mut flipped = original.clone();
    let middle = flipped.len() / 2;
    flipped[middle] ^= 1;
    assert_eq!(check(flipped).err(), Some(VaultError::Corrupt));
    assert_eq!(
        check(original[..original.len() - 20].to_vec()).err(),
        Some(VaultError::Corrupt)
    );
    let header = 32;
    let sealed = CHUNK + 16;
    let mut swapped = original.clone();
    let (first, second) = swapped[header..header + 2 * sealed].split_at_mut(sealed);
    first.swap_with_slice(second);
    assert_eq!(check(swapped).err(), Some(VaultError::Corrupt));
    // A different key cannot read it either.
    let other = Vault::of_library(dir.path().join("other").as_path());
    fs::create_dir_all(dir.path().join("other")).unwrap();
    let other_key = other.create("another password", FAST).unwrap();
    assert!(VaultReader::open(&other_key, &encrypted)
        .and_then(|mut reader| reader.read_range(0, 10))
        .is_err());
}

#[test]
fn items_restore_with_their_cover_and_delete() {
    let dir = library();
    let root = dir.path();
    let vault = Vault::of_library(root);
    let key = vault.create("correct horse", FAST).unwrap();
    let source = root.join("temp/Film.mp4");
    let data = pattern(CHUNK + 3);
    fs::write(&source, &data).unwrap();
    let cover = root.join("temp/Film.jpg");
    fs::write(&cover, b"\xFF\xD8cover").unwrap();
    let item = add(&vault, &key, &source, Some(&cover), "Film");
    assert!(item.has_cover);
    assert_eq!(
        vault.cover(&key, &item.id).unwrap().unwrap(),
        b"\xFF\xD8cover"
    );
    // A video named Film is already in the library: the restore is numbered.
    fs::write(root.join("video/Film.mp4"), b"other").unwrap();

    let restored = vault.restore(&key, &item.id, root).unwrap();

    assert_eq!(restored, "video/Film (2).mp4");
    assert_eq!(fs::read(root.join(&restored)).unwrap(), data);
    assert_eq!(
        fs::read(root.join("artwork/Film (2).jpg")).unwrap(),
        b"\xFF\xD8cover"
    );
    assert!(vault.items(&key).unwrap().is_empty());
    assert!(!vault.video_path(&item.id).exists());

    let second = add(&vault, &key, &source, None, "Again");
    vault.delete(&key, &second.id).unwrap();
    assert!(!vault.video_path(&second.id).exists());
    assert_eq!(
        vault.delete(&key, &second.id).err(),
        Some(VaultError::NotFound)
    );
    assert!(vault.reader(&key, "../vault.json").is_err());
}

use qtmedia_app::media::{serve_vault, vault_request};
use qtmedia_app::vault_commands::VaultSession;

#[test]
fn the_session_holds_one_librarys_key_and_locks_when_idle() {
    let dir = library();
    let vault = Vault::of_library(dir.path());
    let key = vault.create("correct horse", FAST).unwrap();
    let session = VaultSession::default();
    assert!(session.key_for(dir.path()).is_none());
    // Unlocking goes through vault_unlock in the app; here the key is set by
    // unlocking and storing like the command does.
    session.set_for_tests(dir.path().to_path_buf(), key);
    assert!(session.key_for(dir.path()).is_some());
    assert!(session.key_for(std::path::Path::new("C:/Other")).is_none());
    assert!(!session.lock_if_idle(std::time::Duration::from_secs(600)));
    assert!(session.lock_if_idle(std::time::Duration::ZERO));
    assert!(session.key_for(dir.path()).is_none());
    assert!(!session.lock());
}

#[test]
fn vault_videos_stream_by_range_and_only_strict_names_are_served() {
    assert_eq!(
        vault_request("/vault/0123456789abcdef0123456789abcdef.mp4"),
        Some(("0123456789abcdef0123456789abcdef".into(), "mp4".into()))
    );
    assert_eq!(
        vault_request("/vault%2F0123456789abcdef0123456789abcdef.MP4").map(|r| r.1),
        Some("mp4".into())
    );
    assert!(vault_request("/vault/../vault.json").is_none());
    assert!(vault_request("/vault/index.qv").is_none());
    assert!(vault_request("/vault/0123456789abcdef0123456789abcdef.exe").is_none());
    assert!(vault_request("/video/Film.mp4").is_none());

    let dir = library();
    let vault = Vault::of_library(dir.path());
    let key = vault.create("correct horse", FAST).unwrap();
    let data = pattern(2 * CHUNK + 99);
    let source = dir.path().join("video/Clip.mp4");
    fs::write(&source, &data).unwrap();
    let item = add(&vault, &key, &source, None, "Clip");

    let response = serve_vault(
        vault.reader(&key, &item.id).unwrap(),
        "mp4",
        "GET",
        Some("bytes=65530-65545"),
    );
    assert_eq!(response.status, 206);
    assert_eq!(response.body, data[65530..=65545]);
    assert!(response
        .headers
        .iter()
        .any(|(name, value)| *name == "Content-Range"
            && value == &format!("bytes 65530-65545/{}", data.len())));
    let whole = serve_vault(vault.reader(&key, &item.id).unwrap(), "mp4", "GET", None);
    assert_eq!(whole.body, data);
    assert_eq!(
        serve_vault(vault.reader(&key, &item.id).unwrap(), "mp4", "POST", None).status,
        405
    );
}

#[test]
fn concurrent_moves_and_deletes_keep_every_item() {
    let dir = library();
    let root = dir.path().to_path_buf();
    let vault = Vault::of_library(&root);
    let key = vault.create("correct horse", FAST).unwrap();
    let keep = add(
        &vault,
        &key,
        &{
            let p = root.join("temp/keep.mp4");
            fs::write(&p, pattern(10)).unwrap();
            p
        },
        None,
        "Keep",
    );
    let doomed = add(
        &vault,
        &key,
        &{
            let p = root.join("temp/doomed.mp4");
            fs::write(&p, pattern(10)).unwrap();
            p
        },
        None,
        "Doomed",
    );

    // Eight moves of ~1 MB each in parallel, plus a delete in the middle.
    let handles: Vec<_> = (0..8)
        .map(|n| {
            let (root, key) = (root.clone(), key.clone());
            std::thread::spawn(move || {
                let source = root.join(format!("temp/clip{n}.mp4"));
                fs::write(&source, pattern(16 * CHUNK + n)).unwrap();
                add(
                    &Vault::of_library(&root),
                    &key,
                    &source,
                    None,
                    &format!("Clip {n}"),
                )
                .id
            })
        })
        .collect();
    vault.delete(&key, &doomed.id).unwrap();
    let added: Vec<String> = handles
        .into_iter()
        .map(|handle| handle.join().unwrap())
        .collect();

    let ids: std::collections::HashSet<String> = vault
        .items(&key)
        .unwrap()
        .into_iter()
        .map(|item| item.id)
        .collect();
    assert_eq!(ids.len(), 9, "{ids:?}");
    assert!(ids.contains(&keep.id) && !ids.contains(&doomed.id));
    assert!(added.iter().all(|id| ids.contains(id)));
}

/// A file another program holds open (without delete sharing) cannot be
/// removed on Windows: the move waits for it, and reports it if it stays.
#[cfg(windows)]
#[test]
fn originals_in_use_are_retried_and_reported() {
    use qtmedia_app::vault_commands::remove_with_retry;
    use std::os::windows::fs::OpenOptionsExt;

    let dir = tempfile::tempdir().unwrap();
    let busy = dir.path().join("busy.mp4");
    fs::write(&busy, b"video").unwrap();
    let open = || {
        fs::OpenOptions::new()
            .read(true)
            .share_mode(1 /* read only */)
            .open(&busy)
            .unwrap()
    };

    let held = open();
    assert!(!remove_with_retry(&busy));
    assert!(busy.exists());
    drop(held);

    // Released after half a second: the retry gets it.
    let held = open();
    let release = std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(500));
        drop(held);
    });
    assert!(remove_with_retry(&busy));
    release.join().unwrap();
    assert!(!busy.exists());
    assert!(remove_with_retry(&dir.path().join("never-existed.mp4")));
}
