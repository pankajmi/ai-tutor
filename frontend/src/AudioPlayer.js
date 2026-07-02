/**
 * AudioPlayer — receives raw f32 PCM audio chunks (24kHz Kokoro output)
 * over a WebSocket and plays them sequentially via AudioContext.
 *
 * Usage:
 *   const player = new AudioPlayer();
 *   await player.start();
 *   // On each binary WS message from the server:
 *   player.enqueue(audioData);  // ArrayBuffer of f32 PCM
 *   // ...
 *   player.stop();
 */

let _playerId = 0;

export class AudioPlayer {
  constructor() {
    this.id = ++_playerId;
    this.audioContext = null;
    this.gainNode = null;
    this.queue = [];
    this.playing = false;
    this.running = false;
    this.chunksReceived = 0;
    this.totalSamples = 0;
    this.debug = true;
  }

  log(msg, ...args) {
    if (this.debug) console.log(`[AudioPlayer#${this.id}] ${msg}`, ...args);
  }

  async start() {
    if (this.running) return;
    this.running = true;
    this.log("starting...");
    this.audioContext = new AudioContext();
    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = 1.0;
    this.gainNode.connect(this.audioContext.destination);
    this._playNext();
    this.log("started, sampleRate:", this.audioContext.sampleRate);
  }

  /**
   * Immediately silence playback on barge-in.
   *
   * Called when server sends {"type": "stop_audio"} — child interrupted Nova.
   * Audio already transmitted to the browser keeps playing unless we act here.
   * Ramps gain to 0 over 30ms (avoids a click/pop), clears the queue, then
   * restores gain so the next response plays at full volume.
   * Does NOT close AudioContext — we need it again when Nova replies.
   */
  stopNow() {
    this.log("stopNow() — barge-in signal from server");
    this.queue = [];
    this.playing = false;
    if (this.gainNode && this.audioContext) {
      const t = this.audioContext.currentTime;
      this.gainNode.gain.cancelScheduledValues(t);
      this.gainNode.gain.setValueAtTime(this.gainNode.gain.value, t);
      this.gainNode.gain.linearRampToValueAtTime(0, t + 0.03);
      setTimeout(() => {
        if (this.gainNode && this.audioContext) {
          const t2 = this.audioContext.currentTime;
          this.gainNode.gain.cancelScheduledValues(t2);
          this.gainNode.gain.setValueAtTime(0, t2);
          this.gainNode.gain.linearRampToValueAtTime(1.0, t2 + 0.05);
        }
      }, 60);
    }
  }

  stop() {
    this.log("stopping, chunksReceived:", this.chunksReceived, "totalSamples:", this.totalSamples);
    this.running = false;
    this.queue = [];
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    this.gainNode = null;
    this.playing = false;
  }

  enqueue(arrayBuffer) {
    const f32 = new Float32Array(arrayBuffer);
    this.chunksReceived++;
    this.totalSamples += f32.length;
    this.log("enqueue chunk", this.chunksReceived, "samples:", f32.length);
    this.queue.push(f32);
    if (!this.playing) {
      this._playNext();
    }
  }

  async _playNext() {
    while (this.running && this.queue.length > 0) {
      this.playing = true;
      const audioData = this.queue.shift();

      const ctxRate = this.audioContext.sampleRate;
      const srcRate = 24000;
      const resampled = ctxRate === srcRate
        ? audioData
        : this._resample(audioData, srcRate, ctxRate);

      const buffer = this.audioContext.createBuffer(1, resampled.length, ctxRate);
      buffer.getChannelData(0).set(resampled);

      const source = this.audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this.gainNode);
      source.start();

      await new Promise((resolve) => {
        source.onended = resolve;
      });
    }
    this.playing = false;
    this.log("queue drained");
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
    return output;
  }
}
