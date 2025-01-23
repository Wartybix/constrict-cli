#!/usr/bin/python3
import sys
import subprocess
import os
import argparse
import struct
import shutil
import datetime

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

"""
Returns a unique file path for the file path given. Ensures that no file is
overwritten, as if the input file path already exists, the file path output
will be in the form of '{file_root}-{n}{file_ext}' where n incremented with every
existing file in the directory.

Do not use if you *want* to overwrite something.
"""
def new_file(file_path):
    final_path = file_path
    root_ext = os.path.splitext(file_path)

    counter = 0
    while os.path.exists(final_path):
        counter += 1
        final_path = f'{root_ext[0]}-{counter}{root_ext[1]}'

    return(final_path)

"""
Returns a suitable resolution preset (i.e. 1080p, 720p, etc.) from a given
bitrate and source resolution. Allows source videos to be shrunk according to
a new, reduced bitrate for optimal perceived video quality. This function should
not return a resolution preset larger than the source resolution (i.e. an
upscaled or stretched resolution).

-If -1 is returned, then the video's source resolution is recommended.
"""
def get_res_preset(bitrate, sourceWidth, sourceHeight, framerate):
    sourcePixels = sourceWidth * sourceHeight # Get pixel count
    bitrateKbps = bitrate / 1000 # Convert to kilobits
    """
    Bitrate-resolution recommendations are taken from:
    https://developers.google.com/media/vp9/settings/vod
    """
    bitrateResMap30 = {
        12000 : (3840, 2160), # 4K
        6000 : (2560, 1440), # 2K
        1800 : (1920, 1080), # 1080p
        1024 : (1280, 720), # 720p
        512 : (640, 480), # 480p
        276 : (640, 360), # 360p
        150 : (320, 240), # 240p
        0 : (192, 144) # 144p
    }
    bitrateResMap60 = {
        18000 : (3840, 2160), # 4K
        9000 : (2560, 1440), # 2K
        3000 : (1920, 1080), # 1080p
        1800 : (1280, 720), # 720p
        750 : (640, 480), # 480p
        276 : (640, 360), # 360p
        150 : (320, 240), # 240p
        0 : (192, 144) # 144p
    }

    bitrateResMap = bitrateResMap30 if framerate <= 30 else bitrateResMap60

    for bitrateLowerBound, resPreset in bitrateResMap.items():
        presetWidth, presetHeight = resPreset[0], resPreset[1]
        presetPixels = presetWidth * presetHeight
        if bitrateKbps >= bitrateLowerBound and sourcePixels >= presetPixels:
            return presetHeight

    return -1

def get_encoding_speed(frameHeight):
    return '2' if frameHeight > 480 else '1'

def get_progress(fileInput, ffmpegCmd):
    pvCmd = subprocess.Popen(['pv', fileInput], stdout=subprocess.PIPE)
    ffmpegCmd = subprocess.check_output(ffmpegCmd, stdin=pvCmd.stdout)
    pvCmd.wait()

def transcode(
    fileInput,
    fileOutput,
    bitrate,
    width,
    height,
    keepFramerate,
    extraQuality
):
    fpsFilter = '' if keepFramerate else ',fps=30'

    pass1Command = [
        'ffmpeg',
            '-y',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', 'pipe:0',
            '-row-mt', '1',
            '-frame-parallel', '1',
            #'-deadline', 'good',
            #'-cpu-used', '4',
            #'-threads', '24',
            '-vf', f'scale={width}:{height}{fpsFilter}',
            '-c:v', 'libx264',
            '-b:v', str(bitrate) + '',
            '-pass', '1',
            '-an',
            '-f', 'null',
            '/dev/null'
    ]
    print(" ".join(pass1Command))
    print(f' Transcoding... (pass 1/2)')
    get_progress(fileInput, pass1Command)

    portrait = height > width
    frameHeight = width if portrait else height

    print(f' frame height: {frameHeight}')

    cpuUsed = get_encoding_speed(frameHeight) if extraQuality else '4'

    pass2Command = [
        'ffmpeg',
            '-y',
            '-hide_banner',
            '-loglevel', 'error',
            '-i', 'pipe:0',
            '-row-mt', '1',
            '-frame-parallel', '1',
            #'-threads', '24',
            #'-deadline', 'good',
            #'-cpu-used', cpuUsed,
            '-vf', f'scale={width}:{height}{fpsFilter}',
            '-c:v', 'libx264',
            '-b:v', str(bitrate) + '',
            '-pass', '2',
            #'-x265-params', 'pass=1',
            '-c:a', 'libopus',
            #'-b:a', '6k',
            #'-ac', '1',
            fileOutput
    ]

    print(" ".join(pass2Command))
    print(f' Transcoding... (pass 2/2)')
    get_progress(fileInput, pass2Command)

def get_framerate(fileInput):
    command = [
        'ffprobe',
            '-v', '0',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
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

def get_cache_dir():
    homeDir = os.path.expanduser('~')
    cacheDir = os.path.join(homeDir, '.cache/constrict/')
    return cacheDir

def make_cache_dir():
    os.makedirs(get_cache_dir(), exist_ok=True)

def clear_cached_file(filename):
    file = os.path.join(get_cache_dir(), filename)
    os.remove(file)

def is_streamable(fileInput):
    command = ['head', fileInput]
    fileHead = subprocess.check_output(command)

    moovBytes = 'moov'.encode('utf-8')
    mdatBytes = 'mdat'.encode('utf-8')

    #print(f'moov found: {moovBytes in fileHead}')
    #print(f'mdat found: {mdatBytes in fileHead}')

    if moovBytes not in fileHead:
        return mdatBytes not in fileHead

    # moov is now confirmed to be present

    if mdatBytes not in fileHead:
        return True

    # mdia is now confirmed to be present

    moovIndex = fileHead.index(moovBytes)
    mdatIndex = fileHead.index(mdatBytes)

    # print(moovIndex)
    # print(mdatIndex)

    # faststart enabled if 'moov' shows up before 'mdia'
    return moovIndex < mdatIndex

def make_streamable(fileInput, fileOutput):
    command = ['qt-faststart', fileInput, fileOutput]
    subprocess.run(command, stdout=subprocess.DEVNULL)

def get_resolution(fileInput):
    command = [
        'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=s=x:p=0',
            fileInput
    ]

    res_bytes = subprocess.check_output(command)
    res = res_bytes.decode('utf-8')
    res_array = res.split('x')
    width = int(res_array[0])
    height = int(res_array[1])

    return (width, height)

"""
Returns the audio bitrate of input file, once it's re-encoded with Opus codec.
"""
def get_audio_bitrate(fileInput, fileOutput):
    transcodeCommand = [
        'ffmpeg',
            '-y',
            '-v', 'error',
            '-i', 'pipe:0',
            '-vn',
            '-c:a', 'libopus',
            #'-b:a', '12k',
            fileOutput
    ]

    display_heading('Getting audio bitrate...')
    get_progress(fileInput, transcodeCommand)
    #subprocess.run(transcodeCommand, capture_output=True, text=True)

    probeCommand = [
        'ffprobe',
            '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=bit_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            fileOutput
    ]

    try:
        bitrateStr = subprocess.check_output(probeCommand)
        return int(bitrateStr)
    except ValueError:
        print(' Could not get valid bitrate.')
        return 0

def bold(text):
    return f'\033[1m{text}\033[0m'

def display_heading(text):
    print(f':: {bold(text)}')

def print_table(data):
    maxKeyLen = 0
    maxValueLen = 0

    for row in data:
        row[0] += ':'

        if len(row[0]) > maxKeyLen:
            maxKeyLen

        maxKeyLen = len(row[0]) if len(row[0]) > maxKeyLen else maxKeyLen
        maxValueLen = len(row[1]) if len(row[1]) > maxValueLen else maxValueLen

    for row in data:
        spacesToAdd = maxKeyLen - len(row[0])
        for i in range(spacesToAdd):
            row[0] += ' '

        spacesToAdd = maxValueLen - len(row[1])
        for i in range(spacesToAdd):
            row[1] = ' ' + row[1]

        print(f' {row[0]}  {row[1]}')

""" TODO:
check for non-existent files (or non-video files) -- exit 1 with error msg
allow different units for desired file size
add input validation for arguments
add overwrite confirmation and argument
add 'source overwrite' mode: -o value same as input file path
change output file format
check for when file size doesnt change
add more error checking for very low target file sizes
see about audio compression / changing sample rate?
add support for bulk compression
support more video formats
perhaps add a fast/slow option?
add 'keep resolution' argument?
add 'general compression' mode - no target file size
reconsider where log and streamable files go (output dir rather than PWD?)
add verbosity options (GUI and quiet)
don't use streamable temp file with quiet verbosity mode
add overwrite-safe default file outputs (streamable file and compressed file)
Add check when video bitrate calculation goes over original bitrate
change how tolerance works
change res preset function to use full width*height resolutions
add AV1 option parameter
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
argParser.add_argument(
    '--extra-quality',
    action='store_true',
    help='Increase image quality at the cost of longer encoding times'
)
args = argParser.parse_args()

startTime = datetime.datetime.now().replace(microsecond=0)

# Tolerance below 8mb
tolerance = args.tolerance or 10
#print(f'Tolerance: {tolerance}')
fileInput = args.file_path
fileOutput = args.output

if fileOutput == None: # i.e., if -o hasn't been passed
    root_ext = os.path.splitext(fileInput)
    fileOutput = new_file(f'{root_ext[0]} (compressed).mp4')

targetSizeMiB = args.target_size
targetSizeKiB = targetSizeMiB * 1024
targetSizeBytes = targetSizeKiB * 1024
targetSizeBits = targetSizeBytes * 8
durationSeconds = get_duration(fileInput)
extraQuality = args.extra_quality

isInputStreamable = is_streamable(fileInput)
streamableInput = 'streamable_input'

if not isInputStreamable:
    display_heading('Creating input stream...')

    root_ext = os.path.splitext(fileInput)
    streamableInput = new_file(f'{root_ext[0]}-stream{root_ext[1]}')

    make_streamable(fileInput, streamableInput)
    fileInput = streamableInput

#print(f'Fast start enabled: {isInputStreamable}')

beforeSizeBytes = os.stat(fileInput).st_size

if beforeSizeBytes <= targetSizeBytes:
    sys.exit("File already meets the target size.")

reductionFactor = targetSizeBytes / beforeSizeBytes

# A method to try to reduce number of attempts taken to compress a file.
# These hardcoded values are based on a 185MiB video I compressed to various
# target sizes, seeing where the compression would start to go over the target
# size or under the target size with 10% tolerance. Anyone with a more
# sophisticated solution to this is welcome to submit a pull request.

# TODO: revisit this (esp. with extra quality mode and keep framerate)

# shrunkSize = targetSizeBits
# if reductionFactor < (18 / 185):
#     print('reducing target by 10%')
#     shrunkSize *= 0.9
# elif reductionFactor > (160 / 185):
#     print('increasing by 30%')
#     targetSizeMiB *= 1.3
# elif reductionFactor > (85 / 185):
#     print('increasing target by 30%')
#     shrunkSize *= 1.3
# elif reductionFactor > (52 / 185):
#     print('increasing target by 20%')
#     shrunkSize *= 1.2
# elif reductionFactor > (30 / 185):
#     print('increasing target by 10%')
#     shrunkSize *= 1.1

targetVideoBitrate = round(targetSizeBits / durationSeconds)

#print(f'Target total bitrate: {targetVideoBitrate}bps')
audioBitrate = get_audio_bitrate(fileInput, fileOutput)

if audioBitrate is None:
    print('\n No audio bitrate found')
else:
    print(f'\n Audio bitrate: {audioBitrate // 1000}Kbps')
    if (targetVideoBitrate - audioBitrate >= 1000):
        targetVideoBitrate -= audioBitrate
        #print('Subtracting audio bitrate from target video bitrate')

targetVideoBitrate *= 0.99
# To account for metadata and such... shouldn't try to use a bitrate EXACTLY on
# target as it'll likely overshoot, and another attempt will have to be made.

# if targetSizeMB < 25:
    #targetVideoBitrate *= 0.95
#     print('Bitrate lowered by 5%')
    # Slightly lower bitrate target to account for file metadata and such.
# elif targetSizeMB > 75:
#     targetVideoBitrate *= 1.05
#     print('Bitrate increased by 5%')

framerate = get_framerate(fileInput)
#print(f'framerate: {framerate}')
keepFramerate = framerate <= 30 or args.keep_framerate
#print(f'keep framerate: {keepFramerate}')
targetFramerate = framerate if keepFramerate else 30

width, height = get_resolution(fileInput)
#print(f'Resolution: {width}x{height}')
pixels = width * height
#print(f'Total pixels: {pixels}')
portrait = width < height

cacheOccupied = False

factor = 0
attempt = 0
while (factor > 1.0 + (tolerance / 100)) or (factor < 1):
    attempt = attempt + 1
    targetVideoBitrate = round((targetVideoBitrate) * (factor or 1))

    if (targetVideoBitrate < 1000):
        if cacheOccupied:
            clear_cached_file(reducedFpsFile)
        sys.exit(f"Bitrate got too low (<1000bps); aborting")

    targetHeight = height
    targetWidth = width

    if True: # if (!keep resolution), later on
        presetHeight = get_res_preset(
            targetVideoBitrate,
            width,
            height,
            targetFramerate
        )

        print(f'Target height {presetHeight}')

        if presetHeight != -1: # If being downscaled:
            targetHeight = presetHeight
            scalingFactor = height / targetHeight
            targetWidth = int(((width / scalingFactor + 1) // 2) * 2)

            if portrait:
                # Swap height and width
                buffer = targetWidth
                targetWidth = targetHeight
                targetHeight = buffer

    displayedRes = targetWidth if portrait else targetHeight

    print()
    display_heading(f'(Attempt {attempt}) compressing to {targetVideoBitrate // 1000}Kbps / {displayedRes}p@{targetFramerate}...')

    #print(f"Attempt {attempt} -- transcoding {fileInput} at bitrate {targetVideoBitrate}bps")

    transcode(
        fileInput,
        fileOutput,
        targetVideoBitrate,
        targetWidth,
        targetHeight,
        keepFramerate,
        extraQuality
    )
    afterSizeBytes = os.stat(fileOutput).st_size
    percentOfTarget = (100 / targetSizeBytes) * afterSizeBytes

    factor = 100 / percentOfTarget

    if (percentOfTarget > 100):
        # Prevent a lot of attempts resulting in above-target sizes
        factor -= 0.05
        #print(f'Reducing factor by 5%')

    print()
    print_table([
        ['New Size', f"{'{:.2f}'.format(afterSizeBytes/1024/1024)}MB"],
        ['Percentage of Target', f"{'{:.0f}'.format(percentOfTarget)}%"]
    ])

if cacheOccupied:
    clear_cached_file(reducedFpsFile)
if not isInputStreamable:
    os.remove(streamableInput)

timeTaken = datetime.datetime.now().replace(microsecond=0) - startTime
print(f"\nCompleted in {timeTaken}.")


