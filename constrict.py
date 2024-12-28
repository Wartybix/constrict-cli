#!/usr/bin/python3
import sys
import subprocess
import os
import argparse
import struct

def get_duration(fileInput):
    return float(
        subprocess.check_output([
            "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                fileInput
        ])[:-1]
    )


def transcode(fileInput, fileOutput, bitrate):
    command = [
        'ffmpeg',
            '-y',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', fileInput,
            '-b:v', str(bitrate) + '',
            '-b:a', str(bitrate) + '',
            '-cpu-used', str(os.cpu_count()),
            '-c:a',
            'copy',
            fileOutput
    ]
    #print(command)
    proc = subprocess.run(
        command,
        capture_output=True,
        # avoid having to explicitly encode
        text=True
    )
    #print(proc.stdout)

def get_framerate(fileInput):
    command = [
        'ffprobe',
        '-v', '0',
        '-of',
        'csv=p=0',
        '-select_streams', 'v:0',
        '-show_entries',
        'stream=r_frame_rate',
        fileInput
    ]
    fps_bytes = subprocess.check_output(
        command
    )
    fps_fraction = fps_bytes.decode('utf-8')
    fps_fraction_split = fps_fraction.split('/')
    fps_numerator = int(fps_fraction_split[0])
    fps_denominator = int(fps_fraction_split[1])
    fps_float = round(fps_numerator / fps_denominator)
    return(fps_float)

""" TODO:
check for non-existent files (or non-video files) -- exit 1 with error msg
allow different units for desired file size
add more error checking for very low target file sizes
perhaps resize video instead of only relying on bitrate?
change framerate to 30fps by default
see about audio compression?
take away audio bitrate from bitrate calculation
add HEVC support
add support for bulk compression
support more video formats
"""

argParser = argparse.ArgumentParser("constrict")
argParser.add_argument(
    'file_path',
    help='Location of the video file to be compressed',
    type=str
)
argParser.add_argument(
    'target_size',
    help='Desired size of the compressed video in MB',
    type=int
)
argParser.add_argument(
    '-t',
    dest='tolerance',
    type=int,
    help='Tolerance of end file size under target in percent (default 10)'
)
argParser.add_argument(
    '-o',
    dest='output',
    type=str,
    help='Destination path of the compressed video file'
)
argParser.add_argument(
    '--keep-framerate',
    action='store_true',
    help='Keep the source framerate; do not lower to 30FPS'
)
args = argParser.parse_args()

# Tolerance below 8mb
tolerance = args.tolerance or 10
#print(f'Tolerance: {tolerance}')
fileInput = args.file_path
fileOutput = args.output or (fileInput + ".crushed.mp4")
targetSizeMB = args.target_size
targetSizeKB = targetSizeMB * 1024
targetSizeBytes = targetSizeKB * 1024
targetSizeBits = targetSizeBytes * 8
durationSeconds = get_duration(args.file_path)
bitrate = round(targetSizeBits / durationSeconds)
beforeSizeBytes = os.stat(fileInput).st_size

if beforeSizeBytes <= targetSizeBytes:
    sys.exit("File already meets the target size.")

keepFramerate = args.keep_framerate
print(f'keep framerate: {keepFramerate}')
framerate = get_framerate(fileInput)
print(f'framerate: {framerate}')

factor = 0
attempt = 0
while (factor > 1.0 + (tolerance / 100)) or (factor < 1):
    attempt = attempt + 1
    bitrate = round((bitrate - 50000) * (factor or 1))

    if (bitrate < 1000):
        sys.exit("Bitrate got too low; aborting")

    print(f"Attempt {attempt} -- transcoding {fileInput} at bitrate {bitrate}bps")

    transcode(fileInput, fileOutput, bitrate)
    afterSizeBytes = os.stat(fileOutput).st_size
    percentOfTarget = (100 / targetSizeBytes) * afterSizeBytes
    factor = 100 / percentOfTarget
    print(
        f"Attempt {attempt} --",
        f"original size: {'{:.2f}'.format(beforeSizeBytes/1024/1024)}MB,",
        f"new size: {'{:.2f}'.format(afterSizeBytes/1024/1024)}MB,",
        f"percentage of target: {'{:.0f}'.format(percentOfTarget)}%,",
        f"bitrate: {bitrate}bps"
    )
print(f"Completed in {attempt} attempts.")
