# Capture the Windows playback mix for a bounded native-game verification run.
# Uses Windows WASAPI directly; no microphone, driver, or package installation.
[CmdletBinding()]
param(
    [switch]$Probe,
    [ValidateRange(1,120)][int]$Seconds = 30,
    [string]$Output,
    [string]$ReadyFile
)
$ErrorActionPreference = 'Stop'
if (-not $Probe -and [string]::IsNullOrWhiteSpace($Output)) {
    throw 'Specify -Output for a recording, or -Probe to inspect the playback endpoint.'
}
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace FfrAudioCapture {
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    class DeviceEnumerator {}
    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDeviceEnumerator {
        [PreserveSig] int EnumAudioEndpoints(int flow, int mask, out IDeviceCollection devices);
        [PreserveSig] int GetDefaultAudioEndpoint(int flow, int role, out IDevice device);
    }
    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDeviceCollection {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int Item(uint index, out IDevice device);
    }
    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IDevice {
        [PreserveSig] int Activate(ref Guid iid, int clsctx, IntPtr activation, [MarshalAs(UnmanagedType.IUnknown)] out object client);
        [PreserveSig] int OpenPropertyStore(int mode, out IntPtr store);
        [PreserveSig] int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        [PreserveSig] int GetState(out int state);
    }
    [ComImport, Guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioClient {
        [PreserveSig] int Initialize(int shareMode, uint flags, long bufferDuration, long periodicity, IntPtr format, IntPtr session);
        [PreserveSig] int GetBufferSize(out uint size);
        [PreserveSig] int GetStreamLatency(out long latency);
        [PreserveSig] int GetCurrentPadding(out uint padding);
        [PreserveSig] int IsFormatSupported(int shareMode, IntPtr format, out IntPtr closest);
        [PreserveSig] int GetMixFormat(out IntPtr format);
        [PreserveSig] int GetDevicePeriod(out long defaultPeriod, out long minimumPeriod);
        [PreserveSig] int Start();
        [PreserveSig] int Stop();
        [PreserveSig] int Reset();
        [PreserveSig] int SetEventHandle(IntPtr handle);
        [PreserveSig] int GetService(ref Guid iid, [MarshalAs(UnmanagedType.IUnknown)] out object service);
    }
    [ComImport, Guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IAudioCaptureClient {
        [PreserveSig] int GetBuffer(out IntPtr data, out uint frames, out uint flags, out ulong devicePosition, out ulong qpcPosition);
        [PreserveSig] int ReleaseBuffer(uint frames);
        [PreserveSig] int GetNextPacketSize(out uint frames);
    }

    public sealed class CaptureInfo {
        public uint ActivePlaybackEndpoints;
        public Dictionary<string,string> DefaultPlaybackEndpoints = new Dictionary<string,string>();
        public int SampleRate, Channels, BitsPerSample, BlockAlign, FormatTag;
        public string StartedUtc, CompletedUtc, Output;
        public long StartQpc, QpcFrequency = Stopwatch.Frequency;
        public ulong FirstPacketQpc100ns;
        public long FramesWritten, SilentFrames, MissingFrames;
        public int Packets, Discontinuities, TimestampErrors;
    }
    public static class Loopback {
        static void Check(int result) { Marshal.ThrowExceptionForHR(result); }
        static void Release(object value) {
            if(value != null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value);
        }
        static void Tag(BinaryWriter writer, string value) { writer.Write(Encoding.ASCII.GetBytes(value)); }
        static void Silence(BinaryWriter writer, long frames, int align) {
            byte[] zero = new byte[align * 4096];
            while(frames > 0) { int n=(int)Math.Min(frames,4096); writer.Write(zero,0,n*align); frames-=n; }
        }
        public static CaptureInfo Run(bool probe, int seconds, string output, string readyFile) {
            if(seconds<1 || seconds>120) throw new ArgumentOutOfRangeException("seconds");
            IDeviceEnumerator enumerator = null; IDeviceCollection devices = null; IDevice device = null;
            IAudioClient client = null; IAudioCaptureClient capture = null; IntPtr format = IntPtr.Zero;
            bool started = false;
            CaptureInfo info = new CaptureInfo();
            try {
                enumerator = (IDeviceEnumerator)new DeviceEnumerator();
                Check(enumerator.EnumAudioEndpoints(0,1,out devices));
                Check(devices.GetCount(out info.ActivePlaybackEndpoints));
                for(int role=0;role<3;role++) {
                    IDevice defaultDevice; string endpointId;
                    Check(enumerator.GetDefaultAudioEndpoint(0,role,out defaultDevice));
                    try { Check(defaultDevice.GetId(out endpointId)); info.DefaultPlaybackEndpoints.Add(new string[]{"console","multimedia","communications"}[role],endpointId); }
                    finally { Release(defaultDevice); }
                }
                // eRender/eConsole: the normal default playback device used by games.
                Check(enumerator.GetDefaultAudioEndpoint(0,0,out device));
                Guid clientId = typeof(IAudioClient).GUID; object activated;
                Check(device.Activate(ref clientId,23,IntPtr.Zero,out activated));
                client = (IAudioClient)activated;
                Check(client.GetMixFormat(out format));
                int extra=(ushort)Marshal.ReadInt16(format,16);
                byte[] waveFormat = new byte[18+extra]; Marshal.Copy(format,waveFormat,0,waveFormat.Length);
                info.FormatTag=(ushort)Marshal.ReadInt16(format,0);
                info.Channels=(ushort)Marshal.ReadInt16(format,2);
                info.SampleRate=Marshal.ReadInt32(format,4);
                info.BlockAlign=(ushort)Marshal.ReadInt16(format,12);
                info.BitsPerSample=(ushort)Marshal.ReadInt16(format,14);
                if(info.SampleRate<=0 || info.BlockAlign<=0 || waveFormat.Length>65536) throw new InvalidDataException("Invalid playback mix format");
                // AUDCLNT_STREAMFLAGS_LOOPBACK + shared mode. Probe does not Start.
                Check(client.Initialize(0,0x00020000,1000000,0,format,IntPtr.Zero));
                Guid captureId=typeof(IAudioCaptureClient).GUID; object service;
                Check(client.GetService(ref captureId,out service)); capture=(IAudioCaptureClient)service;
                if(probe) return info;
                info.Output=Path.GetFullPath(output);
                Directory.CreateDirectory(Path.GetDirectoryName(info.Output));
                if(!String.IsNullOrEmpty(readyFile)) {
                    readyFile=Path.GetFullPath(readyFile);
                    if(File.Exists(readyFile)) throw new IOException("Ready file already exists: "+readyFile);
                    Directory.CreateDirectory(Path.GetDirectoryName(readyFile));
                }
                // CreateNew prevents an accidental overwrite of previous evidence.
                using(FileStream stream=new FileStream(info.Output,FileMode.CreateNew,FileAccess.Write,FileShare.Read))
                using(BinaryWriter writer=new BinaryWriter(stream)) {
                    Tag(writer,"RIFF"); writer.Write(0); Tag(writer,"WAVEfmt "); writer.Write(waveFormat.Length); writer.Write(waveFormat);
                    if((waveFormat.Length&1)!=0) writer.Write((byte)0);
                    Tag(writer,"fact"); writer.Write(4); long factPosition=stream.Position; writer.Write(0);
                    Tag(writer,"data"); long dataSizePosition=stream.Position; writer.Write(0); long dataStart=stream.Position;
                    long totalFrames=(long)seconds*info.SampleRate;
                    Check(client.Start()); started=true;
                    info.StartQpc=Stopwatch.GetTimestamp(); info.StartedUtc=DateTime.UtcNow.ToString("o");
                    if(!String.IsNullOrEmpty(readyFile)) File.WriteAllText(readyFile,info.StartedUtc,Encoding.UTF8);
                    bool first=true; ulong expectedDevicePosition=0;
                    while((Stopwatch.GetTimestamp()-info.StartQpc)/(double)Stopwatch.Frequency < seconds) {
                        uint available; Check(capture.GetNextPacketSize(out available));
                        while(available>0) {
                            IntPtr data; uint frames,flags; ulong devicePosition,qpcPosition;
                            Check(capture.GetBuffer(out data,out frames,out flags,out devicePosition,out qpcPosition));
                            try {
                                info.Packets++;
                                if((flags&1)!=0) info.Discontinuities++;
                                if((flags&4)!=0) info.TimestampErrors++;
                                long gap=0;
                                if(first) {
                                    info.FirstPacketQpc100ns=qpcPosition;
                                    if((flags&4)==0) {
                                        double elapsed=qpcPosition/10000000.0-info.StartQpc/(double)Stopwatch.Frequency;
                                        gap=(long)Math.Round(Math.Max(0,elapsed)*info.SampleRate);
                                    }
                                    first=false;
                                } else if(devicePosition>expectedDevicePosition) gap=(long)(devicePosition-expectedDevicePosition);
                                gap=Math.Min(gap,Math.Max(0,totalFrames-info.FramesWritten));
                                if(gap>0) { Silence(writer,gap,info.BlockAlign); info.FramesWritten+=gap; info.MissingFrames+=gap; }
                                int count=(int)Math.Min(frames,Math.Max(0,totalFrames-info.FramesWritten));
                                if((flags&2)!=0) { Silence(writer,count,info.BlockAlign); info.SilentFrames+=count; }
                                else if(count>0) { byte[] bytes=new byte[count*info.BlockAlign]; Marshal.Copy(data,bytes,0,bytes.Length); writer.Write(bytes); }
                                info.FramesWritten+=count; expectedDevicePosition=devicePosition+frames;
                            } finally { Check(capture.ReleaseBuffer(frames)); }
                            Check(capture.GetNextPacketSize(out available));
                        }
                        Thread.Sleep(5);
                    }
                    Check(client.Stop()); started=false;
                    long trailing=totalFrames-info.FramesWritten;
                    Silence(writer,trailing,info.BlockAlign); info.SilentFrames+=trailing; info.FramesWritten+=trailing;
                    long dataSize=stream.Position-dataStart;
                    stream.Position=dataSizePosition; writer.Write(checked((int)dataSize));
                    stream.Position=factPosition; writer.Write(checked((int)info.FramesWritten));
                    stream.Position=4; writer.Write(checked((int)(stream.Length-8)));
                    writer.Flush();
                }
                info.CompletedUtc=DateTime.UtcNow.ToString("o");
                return info;
            } finally {
                if(started && client!=null) client.Stop();
                if(format!=IntPtr.Zero) Marshal.FreeCoTaskMem(format);
                Release(capture); Release(client); Release(device); Release(devices); Release(enumerator);
            }
        }
    }
}
'@
$captureInfo = [FfrAudioCapture.Loopback]::Run($Probe.IsPresent, $Seconds, $Output, $ReadyFile)
$captureJson = $captureInfo | ConvertTo-Json -Depth 4
if (-not $Probe) {
    [IO.File]::WriteAllText($captureInfo.Output + '.json', $captureJson)
}
$captureJson
