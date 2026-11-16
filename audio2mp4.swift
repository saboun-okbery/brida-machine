// audio2mp4 <in audio> <out.mp4> — wraps audio into an mp4 with a tiny black video track
// (the board's asset store accepts video, not audio). AAC mono 64 kbps, 16x16 H.264 at 1 fps.
import AVFoundation
import CoreVideo

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: audio2mp4 <in> <out.mp4>"); exit(2) }
let inURL = URL(fileURLWithPath: args[1]), outURL = URL(fileURLWithPath: args[2])
try? FileManager.default.removeItem(at: outURL)

let asset = AVURLAsset(url: inURL)
guard let aTrack = asset.tracks(withMediaType: .audio).first else { print("no audio track"); exit(1) }
let duration = asset.duration

let reader = try AVAssetReader(asset: asset)
let rOut = AVAssetReaderTrackOutput(track: aTrack, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM])
reader.add(rOut)

let writer = try AVAssetWriter(outputURL: outURL, fileType: .mp4)
let vIn = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264, AVVideoWidthKey: 16, AVVideoHeightKey: 16])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: vIn, sourcePixelBufferAttributes: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA, kCVPixelBufferWidthKey as String: 16, kCVPixelBufferHeightKey as String: 16])
let aIn = AVAssetWriterInput(mediaType: .audio, outputSettings: [
    AVFormatIDKey: kAudioFormatMPEG4AAC, AVNumberOfChannelsKey: 1, AVSampleRateKey: 44100, AVEncoderBitRateKey: 64000])
vIn.expectsMediaDataInRealTime = false
aIn.expectsMediaDataInRealTime = false
writer.add(vIn); writer.add(aIn)

reader.startReading()
writer.startWriting()
writer.startSession(atSourceTime: .zero)

var pb: CVPixelBuffer?
CVPixelBufferCreate(nil, 16, 16, kCVPixelFormatType_32BGRA, nil, &pb)
CVPixelBufferLockBaseAddress(pb!, [])
memset(CVPixelBufferGetBaseAddress(pb!), 0, CVPixelBufferGetDataSize(pb!))
CVPixelBufferUnlockBaseAddress(pb!, [])
var t = CMTime.zero
while CMTimeCompare(t, duration) < 0 {
    while !vIn.isReadyForMoreMediaData { usleep(1000) }
    adaptor.append(pb!, withPresentationTime: t)
    t = CMTimeAdd(t, CMTime(value: 1, timescale: 1))
}
vIn.markAsFinished()

while let sb = rOut.copyNextSampleBuffer() {
    while !aIn.isReadyForMoreMediaData { usleep(1000) }
    aIn.append(sb)
}
aIn.markAsFinished()
writer.endSession(atSourceTime: duration)
let sem = DispatchSemaphore(value: 0)
writer.finishWriting { sem.signal() }
sem.wait()
if writer.status != .completed { print("failed: \(String(describing: writer.error))"); exit(1) }
print(String(format: "%.2f", CMTimeGetSeconds(duration)))
