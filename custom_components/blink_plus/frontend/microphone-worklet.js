// Downsample microphone input to 16 kHz mono PCM, in 100 ms packets.
class CameraMicrophone extends AudioWorkletProcessor {
  constructor() {
    super();
    this.packet = new Int16Array(1600);
    this.offset = 0;
    this.phase = 0;
    this.total = 0;
    this.count = 0;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels || !channels.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i] / channels.length;
      this.total += sample;
      this.count++;
      this.phase += 16000;
      if (this.phase >= sampleRate) {
        const value = Math.max(-1, Math.min(1, this.total / this.count));
        this.packet[this.offset++] = Math.round(value * (value < 0 ? 32768 : 32767));
        this.total = 0;
        this.count = 0;
        this.phase -= sampleRate;
        if (this.offset === this.packet.length) {
          this.port.postMessage(this.packet.buffer, [this.packet.buffer]);
          this.packet = new Int16Array(1600);
          this.offset = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("camera-microphone", CameraMicrophone);
