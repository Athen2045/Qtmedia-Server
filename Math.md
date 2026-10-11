# Math (rough work)

My scratch notes for the Qtmedia music player engine: the signals-and-systems
ideas, the formulas I tried, and the ones I kept. This is rough work, not a
report. Where the code and these notes disagree, the code is right
(`QtmediaApp/src-tauri/src/audio/`), and I should fix the notes.

Tags I use:

- **[kept]** is in the code now.
- **[tried]** was attempted or measured, then changed. The reason is written
  next to it.
- **[todo]** is an idea I haven't built.

Symbols: $f_s$ = sample rate (Hz), $C$ = channels, $b$ = bits per sample,
$N$ = frames (1 frame = one sample on every channel), $g$ = linear gain.

---

## 0. The whole system as a block diagram

The first thing I did was draw the pipeline as a chain of systems, like in
the S&S course:

```text
x[n] ─▶ [decode] ─▶ [int→float] ─▶ [resample] ─▶ [mix + gain] ─▶ [quantise/pack] ─▶ [ring 2 s] ─▶ DAC
         symphonia                   rubato FFT                                         rtrb        WASAPI
```

Every box except the ring is LTI or memoryless, apart from rounding (nonlinear)
and the ring (a pure delay). Key realisation: to get "bit-perfect" output,
every middle box has to be the **identity system**. So bit-perfect means
exclusive mode, an integer source, the same $f_s$, the same $C$, $g = 1$, and
no float conversion. If anything differs, some box is not the identity and
the samples change.

---

## 1. How samples are stored

### 1.1 Left-justified integers [kept]

FLAC gives integers of different widths (16, 24 bits). Instead of carrying
different types around, I store everything as `i32` with the value pushed to
the top:

$$
s = v \cdot 2^{\,32-b}
$$

So 16-bit is `v << 16` and 24-bit is `v << 8`. Now every depth has the same
full scale ($2^{31}$), and putting a sample into a smaller container is just
"take the top bytes". Nice, because no multiplication is needed on the
bit-perfect path.

### 1.2 int → float [kept]

$$
x = \frac{s}{2^{31}}, \qquad s \in [-2^{31},\, 2^{31}-1] \;\Rightarrow\; x \in [-1,\; 1-2^{-31}]
$$

### 1.3 float → int [kept]

For MP3 (decoded as float) going to an integer device:

$$
v = \operatorname{round}\!\big(\operatorname{clamp}(x,-1,1)\cdot(2^{\,b-1}-1)\big), \qquad s = v \cdot 2^{\,32-b}
$$

Mistake I almost made: scaling by $2^{b-1}$ instead of $2^{b-1}-1$. Then
$x = +1.0$ gives $2^{b-1}$, which doesn't fit and wraps to the most negative
value: a full-scale click. With $2^{b-1}-1$ it's symmetric, and $-1$ maps to
$-(2^{b-1}-1)$.

Yes, this isn't the exact inverse of 1.2. That's fine: only lossy files go
this way, and they're never bit-perfect anyway.

### 1.4 Packing into the device container [kept]

$$
m = (-1) \ll (32 - b_{\text{valid}}), \qquad \text{bytes} = \operatorname{LE}(s \mathbin{\&} m)[\,4-w\,..\,4\,]
$$

Here $w$ is the container width in bytes. "24-in-32" means a 32-bit
container with 24 valid bits, so the low byte is just zero. As long as the
device container is at least as wide as the source, this is lossless.

### 1.5 Why I never drop bits (quantisation SNR)

The standard result for a full-scale sine and uniform quantisation error:

$$
\text{SNR} \approx 6.02\,b + 1.76 \text{ dB}
$$

Quick derivation so I remember it:

- The step is $\Delta = 2/2^b$.
- The error is uniform on $[-\Delta/2, \Delta/2]$, so its power is
  $\Delta^2/12$.
- The sine's power is $1/2$.
- $\text{SNR} = \frac{1/2}{\Delta^2/12} = \frac{3}{2}\,2^{2b}$. In dB:
  $10\log_{10}(1.5) + 20b\log_{10}2 = 1.76 + 6.02b$.

| $b$ | SNR |
| --- | --- |
| 16 | ≈ 98.1 dB |
| 24 | ≈ 146.3 dB |

Truncating 24 → 16 bits throws away about 48 dB of resolution that can never
come back. So the engine only offers device layouts with
$b_{\text{valid}} \ge b$.

### 1.6 Dither [todo]

Right now float → int just rounds. The textbook fix is TPDF dither: add
noise that is the sum of two independent uniform $\pm\frac{1}{2}$ LSB
variables before rounding. That makes the error's first two moments
independent of the signal (Lipshitz et al.). It only affects MP3 played on an
exclusive integer device, so it's low priority.

---

## 2. Choosing the output format

### 2.1 Candidate layouts [kept]

Integer layouts as (container, valid) bits, smallest first:
$(16,16), (24,24), (32,24), (32,32)$.

- An integer source with $b$ bits only gets layouts with
  $b_{\text{valid}} \ge b$.
- A lossy source tries float first, then integers from widest to smallest.

### 2.2 Bit-perfect as one boolean [kept]

$$
\text{bitPerfect} = \text{exclusive} \wedge \text{lossless} \wedge \neg\text{bluetooth} \wedge (f_{\text{out}} = f_{\text{src}}) \wedge \neg\text{float} \wedge (b_{\text{valid}} \ge b) \wedge (g \ge 1)
$$

The code checks the terms in this order, and the first false one is shown
to the user as the reason: `shared_mode`, `lossy_source`,
`bluetooth_output`, `resampled`, `float_output`,
`exclusive_bits_unsupported`, `software_volume`.

### 2.3 Rate families [kept]

Two rates are in the same family when one divides the other:

$$
\text{sameFamily}(a,b) \iff \min(a,b) > 0 \;\wedge\; \max(a,b) \bmod \min(a,b) = 0
$$

| Family | kHz |
| --- | --- |
| 44.1k | 44.1, 88.2, 176.4, 352.8 |
| 48k | 48, 96, 192, 384 |

Converting between families is the annoying case:

$$
\frac{48000}{44100} = \frac{160}{147}
$$

(gcd = 300). As a polyphase system that's up by $L = 160$, down by
$M = 147$: a much bigger filter bank than a clean ×2.

### 2.4 Which rate to resample to [kept]

If the device can't take the source rate and the user allows resampling,
the engine tries these in order:

1. the lowest same-family rate $\ge f_{\text{src}}$;
2. the lowest rate $\ge f_{\text{src}}$;
3. the highest same-family rate $< f_{\text{src}}$;
4. the highest rate $< f_{\text{src}}$.

Reasoning:

- Going up never needs an anti-aliasing cut of the source's own band.
  Nyquist only gets higher, so no content above the new $f_s/2$ is lost.
- Integer ratios give the simplest, most predictable filter.

Worked example: the source is 88.2 kHz and the device takes {48, 96, 192}
kHz. No family member is available (176.4 is missing), so rule 2 gives
**96 kHz**.

The default policy is still *Strict*. On a mismatch it falls back to shared
mode and says why (`exclusive_rate_unsupported`) instead of resampling.

---

## 3. Resampling

### 3.1 Which resampler [kept]

I use rubato's `Fft` resampler with a fixed ratio and 1024-frame input
chunks. The ratio $f_{\text{out}}/f_{\text{in}}$ is constant for the whole
track, so a synchronous resampler is enough. An asynchronous one (sinc
interpolation with a ratio that can change) is only needed to chase a
drifting clock, and the engine never does that.

### 3.2 Getting the length exactly right [kept]

The ideal output length:

$$
N_{\text{out}} = \left\lceil \frac{N_{\text{in}} \cdot f_{\text{out}}}{f_{\text{in}}} \right\rceil
$$

The filter has a delay of $D$ output frames (`output_delay()`), so:

- the first $D$ frames are thrown away;
- at the end, empty partial chunks flush the tail until $N_{\text{out}}$
  frames exist;
- any excess frames are cut.

Net delay 0, length error 0.

Sanity check on real hardware: 0.25 s at 44.1 kHz is 11,025 frames, and
$11025 \cdot 48000/44100 = 12000$. The probe printed **12,000**.

### 3.3 Gapless and the resampler [kept]

Between gapless tracks with the same source format, the resampler state
just continues. Flushing it would add the tail padding in the middle of an
album. It is only reset on seek and at the real end of the stream.

---

## 4. Channel mapping [kept]

| Case | Rule |
| --- | --- |
| $C_{in}=C_{out}$ | $y_c = g\,x_c$ |
| $C_{out}=1$ | $y = \dfrac{g}{C_{in}}\sum_c x_c$ |
| $C_{in}=1$ | $y_0=y_1=g\,x_0$, others $0$ |
| otherwise | copy the shared channels, silence the rest |

Notes:

- Stereo → mono averages instead of summing. If $L = R = 1$, a sum would
  give 2 and clip.
- Mono → stereo copies at full level rather than $1/\sqrt{2}$ (the
  constant-power pan law). Mono files then play as loud as stereo ones,
  which is what you expect from a music player.

---

## 5. Volume

### 5.1 Linear slider [kept]

The slider value is the amplitude gain $g \in [0,1]$:

$$
G_{\text{dB}} = 20\log_{10} g
$$

| $g$ | dB |
| --- | --- |
| 1.0 | 0 |
| 0.8 (default) | −1.94 |
| 0.5 | −6.02 |
| 0.1 | −20 |

### 5.2 Where to multiply [tried → kept]

- **[tried]** Gain in the converter, on the decoder thread. Problem: the
  converter writes about 2 s ahead into the ring, so moving the slider was
  heard **up to 2 s later**. In system terms, the gain sat before a 2 s
  delay line, and the control change had to travel through it.
- **[kept]** For float outputs (shared mode), the gain moves to the
  renderer, after the ring. The delay is now one device period (a few ms).
- For exclusive integer output with the optional "exclusive volume", the
  gain stays in the converter. Scaling packed integers at the end would mean
  quantising again.

$$
(g_{\text{conv}},\, g_{\text{render}}) = \begin{cases} (1,\, g) & \text{float output} \\ (g,\, 1) & \text{integer output} \end{cases}
$$

In strict exclusive mode $g = 1$, and the slider is locked ("use your
amplifier or DAC volume"). Any $g < 1$ breaks bit-perfect, by 2.2.

### 5.3 Perceptual taper [todo]

Loudness is roughly logarithmic, so with a linear slider most of the change
you can hear is in the bottom ~20 %. Options I wrote down:

- cubic: $g = s^3$;
- a dB taper over a range $R$: $g = 10^{\,R(s-1)/20}$ with $R \approx 60$ dB,
  forcing $g = 0$ at $s = 0$.

### 5.4 Loudness normalisation [todo]

ReplayGain or EBU R128 track and album gain. Catch: any gain $\neq 1$ breaks
bit-perfect, so it would have to be off in exclusive mode.

---

## 6. Buffers and timing

### 6.1 Ring size [kept]

2 s of audio already in the device's format:

$$
B = 2 \cdot f_s \cdot C \cdot \frac{\text{container bits}}{8}
$$

| Format | $B$ |
| --- | --- |
| 44.1 kHz, 16-bit, stereo | 352,800 bytes |
| 96 kHz, 24-in-32, stereo | 1,536,000 bytes |

The render thread never allocates or locks after the first prefill.
Real-time rule: no unbounded operations in the audio callback.

### 6.2 Device period [tried → kept]

$$
T_{\text{100ns}} = \frac{N_{\text{period}} \cdot 10^{7}}{f_s}
$$

- **[tried]** The Windows default period of 10 ms. At 48 kHz that's 480
  frames and works. At 44.1 kHz it's 441 frames, not aligned, so exclusive
  init failed with `AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED` (0x88890019) for the
  whole 44.1k family. Took me a while to see it only happened with 44.1k
  files.
- **[kept]** `calculate_aligned_period_near(3/2 · min_period, 128)`. If init
  still fails, retry with the aligned buffer size the failed client
  reports.
- **[tried]** Partial writes in exclusive event mode, which the driver
  rejects. **[kept]** Always write whole buffers and pad with silence (6.4).

### 6.3 Playback position [kept]

Position comes from frames the device **actually played**, not frames
decoded. Decoded frames run up to 2 s ahead.

$$
t = t_0 + \frac{P - F_0}{f_s}
$$

- $P$ is the real frames played in this session.
- $F_0$ is the session frame where the current track starts (non-zero after
  a gapless join).
- $t_0$ is the track time at $F_0$ (the seek target).

### 6.4 Removing the silence padding from the clock [kept]

Each write records $r$ real frames and $z$ padding frames, with the padding
saved as a span $(\text{start}, z)$. When the device reports $P_{dev}$:

$$
P = \min\!\big(P_{dev} - Z_{\text{done}} - Z_{\text{partial}},\; R\big)
$$

$Z_{\text{done}}$ is the padding spans fully played, $Z_{\text{partial}}$ is
the part of the current span already played, and $R$ is the total real
frames written. Without this, the progress bar crept forward during
underruns.

### 6.5 Packing session + position in one atomic [kept]

$$
w = (\text{session} \ll 48) \;|\; (\text{frames} \mathbin{\&} (2^{48}-1))
$$

This way the control thread can't read a new session id together with the
old session's frame count.

How long until 48 bits overflow? At the worst case of 384 kHz:
$2^{48}/384000 \approx 7.33\times10^{8}$ s, about **23 years**. Fine. The
16-bit session id wraps after 65,536 sessions, but only "is it equal to the
current id" is ever checked, so wrapping doesn't matter.

### 6.6 Loop rates [kept]

| What | Value | Why |
| --- | --- | --- |
| Normal control tick | 250 ms | cheap when idle |
| Fast tick | 10 ms | used while a track end or gapless join is due |
| `Position` events | ≤ 4 Hz | enough for a progress bar |
| Release device after pause | 30 s | gives an exclusive device back to other apps |

---

## 7. Seeking and gapless

### 7.1 Sample-accurate seek [kept]

$$
F^{*} = \operatorname{round}(t \cdot f_s), \quad F^{*} \leftarrow \min(F^{*}, N_{\text{total}})
$$

The demuxer can only land on a packet boundary, $F_{\text{land}} \le F^{*}$.
The decoder then drops

$$
\Delta = \max(0,\, F^{*} - F_{\text{land}})
$$

frames. Test: seeking to 0.1 s at 44.1 kHz lands on exactly frame
**4,410**.

### 7.2 MP3 encoder delay and padding [kept]

MP3 encodes in 1152-sample frames and the encoder adds silence at both ends.
The LAME/Xing header records how much. symphonia trims it, so a 0.25 s test
tone at 44.1 kHz decodes to exactly **11,025** frames, not "some multiple of
1152 with silence".

### 7.3 Gapless join [tried → kept]

If the next track negotiates the same output, the decoder writes it into the
**same ring** right after the current one and reports the join frame
$F_{\text{join}}$. The UI switches tracks when $P \ge F_{\text{join}}$
(6.3).

- In shared mode, any rates can join, because everything is resampled to
  the mix format anyway.
- In exclusive mode, a different rate or depth needs a device reopen, which
  leaves a short gap.

**[tried]** Sending the next track after the session had started. On very
short tracks, the decoder hit the end before the message arrived, and the
join was missed (a race). **[kept]** The next track is sent together with
the session start.

---

## 8. What the hardware actually did

| Device | What happened |
| --- | --- |
| Realtek (laptop, exclusive) | 44.1–192 kHz at 16, 24 and 24-in-32 bits all play. No 32-bit integer or float. Nothing above 192 kHz. 16/44.1 → 16/44.1 joined gaplessly. 16/44.1 → 24/96 reopened at 96 kHz, both bit-perfect. |
| AirBass Bluetooth (A2DP) | The driver says yes to every exclusive format, then refuses at `Initialize` (0x88890008). Falls back to shared mode with `exclusive_format_unsupported`. Shared 44.1 → 96 kHz joined gaplessly. Bluetooth re-encodes to a lossy codec, so it is never bit-perfect. |
| Bluetooth hands-free endpoint | Detected from service UUID `0000111E-…`. Flagged as call quality (mono). |

All tests used −30 dBFS tones (to protect my ears) and 0.25 s fixtures.

Lesson: never trust "supported" from a driver; open the device and see.

---

## 9. Stable volume for video (Web Audio)

Not the native engine (video audio stays in the webview), but it's the other
piece of DSP in the player, so it goes here.

### 9.1 Why

A YouTube clip sounded much louder on YouTube than my downloaded copy.
Measured with FFmpeg's `ebur128`:

| Track | Integrated | LRA | Quiet parts |
| --- | --- | --- | --- |
| My download (original mix) | −16.6 LUFS | 13.5 LU | −40 to −28 LUFS |
| YouTube "Stable volume" (DRC track) | −14.9 LUFS | 7.3 LU | lifted 10–15 dB |

YouTube's −14 LUFS normalisation only turns loud videos down, and this one is
quieter than −14, so normalisation wasn't the cause. The difference was
**dynamic range compression**: the loudness range (LRA) is almost halved.

### 9.2 The chain [kept]

```text
source ─▶ compressor ─▶ make-up gain ─▶ limiter ─▶ speakers
```

| Stage | Threshold | Knee | Ratio | Attack | Release |
| --- | --- | --- | --- | --- | --- |
| Compressor | −30 dB | 10 dB | 2:1 | 10 ms | 400 ms |
| Make-up | +2 dB → $10^{2/20} \approx 1.259$ | | | | |
| Limiter | −1.5 dB | 0 | 20:1 | 2 ms | 100 ms |

The textbook soft-knee static curve (Giannoulis, Massberg & Reiss), with
$x, y$ in dB:

$$
y = \begin{cases}
x & 2(x-T) < -W \\[2pt]
x + \left(\frac{1}{R}-1\right)\dfrac{(x - T + W/2)^2}{2W} & |2(x-T)| \le W \\[6pt]
T + \dfrac{x-T}{R} & 2(x-T) > W
\end{cases}
$$

With $T=-30$, $W=10$ and $R=2$, the knee runs from −35 to −25 dB.

Example: an input of −10 dB is above the knee, so the output is
$-30 + 20/2 = -20$ dB before make-up.

Attack and release smoothing: a one-pole envelope follower,

$$
\alpha = e^{-1/(\tau f_s)}, \qquad e_n = \alpha\, e_{n-1} + (1-\alpha)\,|x_n|
$$

Here $\tau$ is the attack time when the level rises and the release time when
it falls.

**Catch:** Chromium's `DynamicsCompressorNode` doesn't follow this curve
exactly. It has its own knee shape and adds **automatic make-up gain**. So
I couldn't design from the formula alone. I only added +2 dB of my own
make-up and tuned by measuring.

### 9.3 Tuning by measurement [tried → kept]

Offline renders in Chromium, steady tones in, gain measured:

| In (dBFS) | −50 | −40 | −30 | −24 | −18 | −12 | −6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gain (dB) | +10.3 | +10.3 | +10.1 | +8.4 | +5.5 | +2.6 | −0.4 |
| Out (dBFS) | −39.7 | −29.7 | −19.9 | −15.6 | −12.5 | −9.4 | −6.4 |

What I read from it:

- Below the threshold the gain is flat at about +10.3 dB. That's Chromium's
  automatic make-up (about 8.3 dB) plus my +2 dB.
- From −30 to −6 dB in (24 dB), the output goes from −19.9 to −6.4 dB
  (13.5 dB). That's an effective ratio of about **1.78:1** for the whole
  chain, a bit under 2:1 because of the knee.
- The total range of 44 dB in became 33.3 dB out.
- Peaks stayed at or below −0.8 dBFS, so the limiter does its job.

Checked inside the real app, on the same film scene at 40–46 s:

| | Off | On | Change |
| --- | --- | --- | --- |
| RMS | −28.1 dB | −21.3 dB | +6.8 dB |
| Peaks | −10.9 dB | −6.7 dB | |

### 9.4 Rejected idea

I rejected sending video audio through the native engine. I'd need A/V sync
between the webview's video clock and the Rust output clock (two clocks that
drift). The engine also only decodes FLAC/MP3, while video audio is Opus,
AAC or Dolby. Too much work for no gain.

---

## 10. Small maths elsewhere in the player

**Lyrics timing (LRC).** For `[mm:ss.xx]` with an `[offset:±ms]` tag $o$
(positive means show earlier):

$$
t = 60m + s + \text{frac} - \frac{o}{1000}, \qquad t \leftarrow \max(0, t)
$$

The current line is $\max\{i : t_i \le t_{\text{now}}\}$. The times are
sorted, so binary search finds it in $O(\log n)$.

**Previous button.** If the position is past 3 s (or it's the first track),
it restarts the song. Otherwise it goes back one track. Same as most players.

**Shuffle.** Fisher–Yates, which makes all $n!$ orders equally likely. The
current song is pinned first, so it's really $(n-1)!$ orders for the rest.
Easy bug to avoid: `swap = random(0..n)` instead of `random(0..i)` gives a
biased shuffle.

**Cover tint colour.** The cover is shrunk to 12×12, pixels with alpha below
128 are skipped, and each remaining pixel gets a "how colourful is it"
weight:

$$
w = 0.15 + \frac{\max(r,g,b)-\min(r,g,b)}{\max(r,g,b)}, \qquad \bar{c} = \frac{\sum w\,c}{\sum w}
$$

The fraction is the HSV saturation. Without the weight, a cover with a big
black border would come out grey. The 0.15 floor means a fully grey cover
still gets an average. If the result is too dark ($\max < 110$), every
channel is scaled by $k = 110/\max(r,g,b)$.

**Fallback colour (no cover art).** A string hash over the title,
$h_{k+1} = (31h_k + c_k) \bmod 2^{32}$, then
$\text{HSL}(h \bmod 360,\ 0.45,\ 0.42)$ → RGB. The same title always gets the
same colour.

---

## 11. To do

- [ ] TPDF dither for float → int in exclusive mode (1.6)
- [ ] Perceptual volume curve (5.3)
- [ ] ReplayGain / R128 for music (5.4)
- [ ] Test exclusive mode on a real external DAC (32-bit, > 192 kHz)
- [ ] Network speakers (Wi-Fi): not designed at all yet

---

## Sources

Textbooks and papers:

1. A. V. Oppenheim and R. W. Schafer, *Discrete-Time Signal Processing*, 3rd
   ed., Pearson, 2010. Sampling, multirate systems (up/down-sampling,
   polyphase), quantisation noise.
2. A. V. Oppenheim, A. S. Willsky and S. H. Nawab, *Signals and Systems*,
   2nd ed., Prentice Hall, 1997. LTI systems, block diagrams, delay
   systems.
3. R. G. Lyons, *Understanding Digital Signal Processing*, 3rd ed., Prentice
   Hall, 2010. Practical resampling and fixed-point notes.
4. D. Giannoulis, M. Massberg and J. D. Reiss, "Digital Dynamic Range
   Compressor Design: A Tutorial and Analysis," *J. Audio Eng. Soc.*, vol.
   60, no. 6, pp. 399–408, 2012. Soft-knee curve and envelope followers.
5. S. P. Lipshitz, R. A. Wannamaker and J. Vanderkooy, "Quantization and
   Dither: A Theoretical Survey," *J. Audio Eng. Soc.*, vol. 40, no. 5,
   pp. 355–375, 1992. TPDF dither.
6. D. E. Knuth, *The Art of Computer Programming, Vol. 2: Seminumerical
   Algorithms*, 3rd ed., Addison-Wesley, 1997, §3.4.2. Fisher–Yates
   shuffle.
7. J. O. Smith III, "Digital Audio Resampling Home Page," CCRMA, Stanford.
   <https://ccrma.stanford.edu/~jos/resample/>

Standards:

8. ITU-R BS.1770, *Algorithms to measure audio programme loudness and
   true-peak audio level*. <https://www.itu.int/rec/R-REC-BS.1770>
9. EBU R 128, *Loudness normalisation and permitted maximum level of audio
   signals*. <https://tech.ebu.ch/publications/r128>
10. W3C, *Web Audio API*, DynamicsCompressorNode.
    <https://www.w3.org/TR/webaudio/#DynamicsCompressorNode>
11. W3C, *CSS Color Module Level 4*, HSL to RGB conversion.
    <https://www.w3.org/TR/css-color-4/#hsl-to-rgb>
12. ReplayGain specification, Hydrogenaudio Knowledgebase.
    <https://wiki.hydrogenaud.io/index.php?title=ReplayGain_specification>

Platform and library docs:

13. Microsoft, "Exclusive-Mode Streams," Core Audio APIs.
    <https://learn.microsoft.com/en-us/windows/win32/coreaudio/exclusive-mode-streams>
14. Microsoft, `IAudioClient::Initialize` (period alignment and
    `AUDCLNT_E_BUFFER_SIZE_NOT_ALIGNED`).
    <https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-initialize>
15. `wasapi` Rust crate. <https://docs.rs/wasapi>
16. `rubato` Rust crate (FFT and sinc resamplers). <https://docs.rs/rubato>
17. Symphonia (pure-Rust audio decoding, gapless support).
    <https://github.com/pdeljanov/Symphonia>
18. `rtrb` real-time ring buffer. <https://docs.rs/rtrb>
19. FFmpeg filters, `ebur128`. <https://ffmpeg.org/ffmpeg-filters.html#ebur128>
20. "Mp3 info tag (LAME tag) specification," encoder delay and padding fields.
    <http://gabriel.mp3-tech.org/mp3infotag.html>
21. "LRC (file format)," Wikipedia.
    <https://en.wikipedia.org/wiki/LRC_(file_format)>
22. D. Lex, "Programming volume controls" (perceptual volume curves).
    <https://www.dr-lex.be/info-stuff/volumecontrols.html>

My own measurements (no external source): the hardware tables in 8, the
tone renders and in-app numbers in 9.3, and the ebur128 readings in 9.1. They
are logged in `QtmediaApp/context.md`.
