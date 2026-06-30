/**
 * AudioStreamer — captures mic audio via getUserMedia, resamples to 16kHz,
 * and sends raw f32 PCM frames over a WebSocket.
 *
 * Usage:
 *   const streamer = new AudioStreamer(ws);
 *   await streamer.start();
 *   // ... later
 *   streamer.stop();
 */

const TARGET_SAMPLE_RATE = 16000;
const FRAME_DURATION_MS = 32;
const FRAME_SAMPLES = Math.floor(TARGET_SAMPLE_RATE * FRAME_DURATION_MS / 1000);

let _streamerId = 0;

export class AudioStreamer {
  constructor(ws, onLevel) {
    this.id = ++_streamerId;
    this.ws = ws;
    this.onLevel = onLevel; // callback(amplitude: 0-1)
    this.mediaStream = null;
    this.audioContext = null;
    this.source = null;
    this.processor = null;
    this.gainSilent = null;
    this.running = false;
    this.accumulator = [];
    this.framesSent = 0;
    this._resumeTimer = null;
    this.debug = true;
  }

  log(msg, ...args) {
    if (this.debug) console.log(`[AudioStreamer#${this.id}] ${msg}`, ...args);
  }

  async start() {
    if (this.running) return;
    this.running = true;
    this.log("starting...");

    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: { ideal: TARGET_SAMPLE_RATE },
          channelCount: 1,
        },
      });
      this.log("getUserMedia OK, tracks:", this.mediaStream.getTracks().length);
    } catch (err) {
      console.error("[AudioStreamer] getUserMedia failed:", err);
      this.running = false;
      throw err;
    }

    this.audioContext = new AudioContext();
    const ctxRate = this.audioContext.sampleRate;
    this.log("AudioContext state:", this.audioContext.state, "sampleRate:", ctxRate);

    // Keep the AudioContext alive — browsers suspend silent contexts
    this._startContextKeepAlive();

    this.source = this.audioContext.createMediaStreamSource(this.mediaStream);

    const bufferSize = 1024;
    this.processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);
    this.gainSilent = this.audioContext.createGain();
    this.gainSilent.gain.value = 0;

    this.source.connect(this.processor);
    this.processor.connect(this.gainSilent);
    this.gainSilent.connect(this.audioContext.destination);

    this.processor.onaudioprocess = (e) => {
      if (!this.running) return;
      const input = e.inputBuffer.getChannelData(0);

      // Report peak amplitude for mic level indicator
      if (this.onLevel) {
        let peak = 0;
        for (let i = 0; i < input.length; i++) {
          const abs = Math.abs(input[i]);
          if (abs > peak) peak = abs;
        }
        this.onLevel(peak);
      }

      const resampled = this._resample(input, ctxRate, TARGET_SAMPLE_RATE);
      for (const frame of resampled) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(frame.buffer);
          this.framesSent++;
        }
      }
    };

    this.log("started");
  }

  /**
   * Periodically resume the AudioContext to prevent the browser from
   * suspending it (Chrome suspends contexts that aren't actively
   * producing audible output).
   */
  _startContextKeepAlive() {
    this._resumeTimer = setInterval(async () => {
      if (!this.running || !this.audioContext) {
        this._stopKeepAlive();
        return;
      }
      if (this.audioContext.state === "suspended") {
        this.log("AudioContext was suspended — resuming...");
        try {
          await this.audioContext.resume();
          this.log("AudioContext resumed");
        } catch (err) {
          console.warn("[AudioStreamer] resume failed:", err);
        }
      }
    }, 1000);
  }

  _stopKeepAlive() {
    if (this._resumeTimer) {
      clearInterval(this._resumeTimer);
      this._resumeTimer = null;
    }
  }

  stop() {
    this.log("stopping, framesSent:", this.framesSent);
    this.running = false;
    this._stopKeepAlive();
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.gainSilent) {
      this.gainSilent.disconnect();
      this.gainSilent = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    if (this.mediaStream) {
      for (const track of this.mediaStream.getTracks()) {
        track.stop();
      }
      this.mediaStream = null;
    }
  }

  _resample(input, srcRate, targetRate) {
    const ratio = targetRate / srcRate;
    const outLen = Math.floor(input.length * ratio);
    const output = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcIdx = i / ratio;
      const lo = Math.floor(srcIdx);
      const hi = Math.min(lo + 1, input.length - 1);
      const frac = srcIdx - lo;
      output[i] = input[lo] * (1 - frac) + input[hi] * frac;
    }

    const frames = [];
    this.accumulator.push(output);
    let combined = this._concatAccumulator();
    while (combined.length >= FRAME_SAMPLES) {
      frames.push(new Float32Array(combined.slice(0, FRAME_SAMPLES)));
      combined = combined.slice(FRAME_SAMPLES);
    }
    this.accumulator = combined.length > 0 ? [combined] : [];
    return frames;
  }

  _concatAccumulator() {
    const totalLen = this.accumulator.reduce((sum, a) => sum + a.length, 0);
    const result = new Float32Array(totalLen);
    let offset = 0;
    for (const arr of this.accumulator) {
      result.set(arr, offset);
      offset += arr.length;
    }
    return result;
  }
}
