//! WASAPI device lookup, capabilities and error mapping.

use wasapi::{
    initialize_mta, AudioClient, Device, DeviceEnumerator, Direction, SampleType, WasapiError,
    WaveFormat,
};
use windows::core::{GUID, HSTRING};
use windows::Win32::Foundation::PROPERTYKEY;
use windows::Win32::Media::Audio::{IMMDeviceEnumerator, MMDeviceEnumerator};
use windows::Win32::System::Com::StructuredStorage::{PropVariantClear, PropVariantToStringAlloc};
use windows::Win32::System::Com::{CoCreateInstance, CoTaskMemFree, CLSCTX_ALL, STGM_READ};

use super::{
    avoid_hands_free, endpoint_transport, map_hresult, DeviceInfo, Endpoint, OutputError, Transport,
};
use crate::audio::format::{DeviceCaps, PcmFormat};

/// `PKEY_Device_ContainerId`: shared by every endpoint of one physical device.
const PKEY_DEVICE_CONTAINER_ID: PROPERTYKEY = PROPERTYKEY {
    fmtid: GUID::from_u128(0x8c7ed206_3f8a_4827_b3ab_ae9e1faefc6c),
    pid: 2,
};

/// Endpoint properties written by the audio endpoint builder: the device
/// instance path of the endpoint's driver (`BTHENUM\{service-uuid}…` for
/// Windows' own Bluetooth drivers), the Bluetooth path recorded by offloading
/// drivers, and the adapter driver description.
const ENDPOINT_PROPERTIES: GUID = GUID::from_u128(0xb3f8fa53_0004_438e_9003_51a46e139bfc);
const PKEY_ENDPOINT_DEVICE_PATH: PROPERTYKEY = PROPERTYKEY {
    fmtid: ENDPOINT_PROPERTIES,
    pid: 2,
};
const PKEY_ENDPOINT_BLUETOOTH_PATH: PROPERTYKEY = PROPERTYKEY {
    fmtid: ENDPOINT_PROPERTIES,
    pid: 39,
};
const PKEY_ENDPOINT_ADAPTER: PROPERTYKEY = PROPERTYKEY {
    fmtid: ENDPOINT_PROPERTIES,
    pid: 6,
};

pub(super) fn map_error(error: WasapiError) -> OutputError {
    match error {
        WasapiError::Windows(error) => map_hresult(error.code().0 as u32),
        WasapiError::UnsupportedFormat | WasapiError::UnsupportedSubformat(_) => {
            OutputError::FormatUnsupported
        }
        WasapiError::DeviceNotFound(_) => OutputError::DeviceLost,
        _ => OutputError::Unavailable,
    }
}

pub(super) fn hresult(error: &WasapiError) -> Option<u32> {
    match error {
        WasapiError::Windows(error) => Some(error.code().0 as u32),
        _ => None,
    }
}

/// Joins the calling thread to the multithreaded apartment (idempotent).
pub(super) fn ensure_com() {
    let _ = initialize_mta();
}

pub(super) fn find_device(id: Option<&str>) -> Result<Device, OutputError> {
    let enumerator = DeviceEnumerator::new().map_err(map_error)?;
    let device = match id {
        Some(id) => enumerator.get_device(id),
        None => enumerator.get_default_device(&Direction::Render),
    }
    .map_err(map_error)?;
    let chosen = device.get_id().map_err(map_error)?;
    if transport_of(&chosen) != Transport::BluetoothHandsFree {
        return Ok(device);
    }
    // Never play through a Hands-Free endpoint (mono call quality); use the
    // same headset's stereo endpoint.
    let endpoints = render_endpoints(&enumerator)?;
    match avoid_hands_free(&chosen, &endpoints) {
        Some(stereo) => enumerator.get_device(&stereo).map_err(map_error),
        None => Err(OutputError::HandsFreeOnly),
    }
}

fn render_endpoints(enumerator: &DeviceEnumerator) -> Result<Vec<Endpoint>, OutputError> {
    let collection = enumerator
        .get_device_collection(&Direction::Render)
        .map_err(map_error)?;
    let mut endpoints = Vec::new();
    for device in &collection {
        let id = device.map_err(map_error)?.get_id().map_err(map_error)?;
        endpoints.push(Endpoint {
            transport: transport_of(&id),
            container: endpoint_string(&id, &PKEY_DEVICE_CONTAINER_ID)
                .map(|value| value.to_ascii_lowercase()),
            id,
        });
    }
    Ok(endpoints)
}

pub(super) fn to_waveformat(format: &PcmFormat) -> WaveFormat {
    let kind = if format.float {
        SampleType::Float
    } else {
        SampleType::Int
    };
    WaveFormat::new(
        format.container_bits.into(),
        format.valid_bits.into(),
        &kind,
        format.rate as usize,
        format.channels.into(),
        None,
    )
}

pub(super) fn from_waveformat(wave: &WaveFormat) -> PcmFormat {
    let container = wave.get_bitspersample();
    let valid = match wave.get_validbitspersample() {
        0 => container,
        valid => valid,
    };
    PcmFormat {
        rate: wave.get_samplespersec(),
        channels: wave.get_nchannels(),
        container_bits: container,
        valid_bits: valid,
        float: matches!(wave.get_subformat(), Ok(SampleType::Float)),
    }
}

fn endpoint_string(id: &str, key: &PROPERTYKEY) -> Option<String> {
    unsafe {
        let enumerator: IMMDeviceEnumerator =
            CoCreateInstance(&MMDeviceEnumerator, None, CLSCTX_ALL).ok()?;
        let device = enumerator.GetDevice(&HSTRING::from(id)).ok()?;
        let store = device.OpenPropertyStore(STGM_READ).ok()?;
        let mut value = store.GetValue(key).ok()?;
        let text = PropVariantToStringAlloc(&value).ok().and_then(|pwstr| {
            let text = pwstr.to_string().ok();
            CoTaskMemFree(Some(pwstr.0.cast()));
            text
        });
        let _ = PropVariantClear(&mut value);
        text
    }
}

pub(super) fn transport_of(id: &str) -> Transport {
    endpoint_transport(
        &endpoint_string(id, &PKEY_ENDPOINT_BLUETOOTH_PATH).unwrap_or_default(),
        &endpoint_string(id, &PKEY_ENDPOINT_DEVICE_PATH).unwrap_or_default(),
        &endpoint_string(id, &PKEY_ENDPOINT_ADAPTER).unwrap_or_default(),
    )
}

/// Active render endpoints, default first marked.
pub fn list_devices() -> Result<Vec<DeviceInfo>, OutputError> {
    ensure_com();
    let enumerator = DeviceEnumerator::new().map_err(map_error)?;
    let default_id = enumerator
        .get_default_device(&Direction::Render)
        .and_then(|device| device.get_id())
        .ok();
    let collection = enumerator
        .get_device_collection(&Direction::Render)
        .map_err(map_error)?;
    let mut devices = Vec::new();
    for device in &collection {
        let device = device.map_err(map_error)?;
        let id = device.get_id().map_err(map_error)?;
        let transport = transport_of(&id);
        // Hands-Free endpoints are never offered: playing through one puts the
        // headset in call mode.
        if transport == Transport::BluetoothHandsFree {
            continue;
        }
        devices.push(DeviceInfo {
            name: device.get_friendlyname().unwrap_or_else(|_| id.clone()),
            transport,
            is_default: default_id.as_deref() == Some(id.as_str()),
            id,
        });
    }
    Ok(devices)
}

/// Production [`DeviceCaps`] for one endpoint.
pub struct WasapiCaps {
    id: String,
    client: AudioClient,
    mix: PcmFormat,
    transport: Transport,
}

impl WasapiCaps {
    /// `None` opens the current default output.
    pub fn open(id: Option<&str>) -> Result<Self, OutputError> {
        ensure_com();
        let device = find_device(id)?;
        let id = device.get_id().map_err(map_error)?;
        let client = device.get_iaudioclient().map_err(map_error)?;
        let mix = from_waveformat(&client.get_mixformat().map_err(map_error)?);
        Ok(Self {
            transport: transport_of(&id),
            id,
            client,
            mix,
        })
    }

    pub fn id(&self) -> &str {
        &self.id
    }

    pub fn transport(&self) -> Transport {
        self.transport
    }
}

impl DeviceCaps for WasapiCaps {
    fn supports_exclusive(&self, format: &PcmFormat) -> bool {
        self.client
            .is_supported_exclusive_with_quirks(&to_waveformat(format))
            .is_ok_and(|accepted| {
                let accepted = from_waveformat(&accepted);
                (
                    accepted.rate,
                    accepted.container_bits,
                    accepted.valid_bits,
                    accepted.float,
                ) == (
                    format.rate,
                    format.container_bits,
                    format.valid_bits,
                    format.float,
                )
            })
    }

    fn mix_format(&self) -> PcmFormat {
        self.mix
    }

    fn is_bluetooth(&self) -> bool {
        self.transport != Transport::Wired
    }
}
