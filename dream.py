import argparse
import bisect
import subprocess
import pathlib
import typing
import shutil
from tempfile import NamedTemporaryFile
import re
import shlex

import gc
import torch.cuda
import toml

from dreamlib import commands

OUTPUT_IMAGE_PATH = pathlib.Path('output.png')
OUTPUT_VIDEO_PATH = pathlib.Path('output.mp4')


def main() -> int:
    ns = parse_args()

    gc.collect()
    torch.cuda.empty_cache()

    output_folder: pathlib.Path = ns.output_folder
    output_name = output_folder.name
    if output_folder.exists() and output_folder.is_dir():
        if ns.force:
            print(f'using existing folder at {output_folder}')
        else:
            print('output folder already exists')
            return 1
    else:
        output_folder.mkdir(parents=True)

    # parse the config file
    config = toml.load(ns.config_path)

    with open(ns.commands_path, 'r') as commands_fp:
        global_options = ""
        curr_cmd_str = ""

        img_dst: typing.Optional[pathlib.Path] = None

        for idx, line in enumerate(commands_fp):
            line = line.strip()
            if line.startswith('#') or len(line) == 0:
                continue
            if line.startswith("GLOBAL:"):
                # set new global options
                global_options = line.split("GLOBAL:")[1]
                continue
            if line.endswith('\\'):
                curr_cmd_str += line.strip()[:-1] + ' '
                continue

            curr_cmd_str += line
            cmd = commands.GenerateVideoCommand.from_input_line(curr_cmd_str)
            cmd.add_options(global_options)

            if not img_dst:
                # if we don't have a previous run, see if we can find a cached image from our last run.
                # this lets us comment out lines in the input script to skip running them (for speed's sake while
                # iterating on later parts of the dream)
                img_dst = find_prev_frame(idx, output_name, output_folder)
            if img_dst:
                # the next video should start from the last frame of this one
                cmd.initial_frame_path = img_dst

            # add configuration
            cmd.add_options_from_config(config['video'])

            # and run that thang, piping stdout out
            ret = commands.run_cmd(cmd)

            if ret != 0:
                print(f'this returned error {ret}: {cmd}')
                return 2

            # now grab the outputs and stick them in our output folder.
            img_dst = output_folder / f"{output_name}{idx}{OUTPUT_IMAGE_PATH.suffix}"
            vid_dst = output_folder / f"{output_name}{idx}{OUTPUT_VIDEO_PATH.suffix}"

            shutil.copy(OUTPUT_IMAGE_PATH, img_dst)
            shutil.copy(OUTPUT_VIDEO_PATH, vid_dst)

            print(f"Generated {img_dst} and {vid_dst}")
            curr_cmd_str = ''

    # make the final video by concatenating all previous
    final_output = output_folder / f"{output_name}{OUTPUT_VIDEO_PATH.suffix}"
    if final_output.exists():
        final_output.unlink()
    clips = list(output_folder.glob(f"{output_name}*{OUTPUT_VIDEO_PATH.suffix}"))
    vid_re = re.compile(output_name + r'(?P<idx>\d+)' + OUTPUT_VIDEO_PATH.suffix)
    clips = sorted(clips, key=lambda path: int(vid_re.match(path.name).group('idx')))

    print(f'Merging {len(clips)} videos...')
    merge_videos(clips, output_folder / f"{output_name}{OUTPUT_VIDEO_PATH.suffix}",
                 audio_path=pathlib.Path(ns.audio_file) if ns.audio_file else None)
    print('Done.')

    return 0


def find_prev_frame(curr_idx: int, output_name: str, output_folder: pathlib.Path) -> typing.Optional[pathlib.Path]:
    # find the image with the index most recent before this one, if it exists

    img_paths = list(output_folder.glob(f"{output_name}*{OUTPUT_IMAGE_PATH.suffix}"))
    img_re = re.compile(output_name + r'(?P<idx>\d+)' + OUTPUT_IMAGE_PATH.suffix)

    def get_file_index(path: pathlib.Path) -> typing.Optional[int]:
        img_match = img_re.match(path.name)
        return int(img_match.group('idx')) if img_match else None

    img_indices = sorted(map(get_file_index, img_paths))
    this_frame_idx = bisect.bisect_left(img_indices, curr_idx)
    if this_frame_idx == 0:
        return None
    return output_folder / f"{output_name}{img_indices[this_frame_idx - 1]}{OUTPUT_IMAGE_PATH.suffix}"


def merge_videos(video_list: typing.Iterable[pathlib.Path], output_path: pathlib.Path,
                 audio_path: pathlib.Path = None) -> None:
    """
    merges an ordered list of clips into one video, with audio on top

    :returns: path to merged video
    """
    # let's use ffmpeg directly. To do so, we need to make a temporary input file of all the files to merge
    with NamedTemporaryFile('w', delete=False) as input_list_file:
        tmp_file_name = input_list_file.name
        lines = [f"file {path.resolve()}\n" for path in video_list]
        print(f'Merging these files\n{lines}')
        input_list_file.writelines(lines)

    # merge the video files
    cmd = ["ffmpeg",
           "-fflags",
           "+igndts",
           "-f",
           "concat",
           "-safe",
           "0",
           "-i",
           tmp_file_name]

    # if audio_path is not None:
    #     cmd.extend([
    #        "-i",
    #        str(audio_path),
    #        # "-map",
    #        # "0",
    #        # "-map",
    #        # "1:a",
    #     ])
    #
    cmd.extend([
           "-c",
           "copy",
           str(output_path),
           "-copytb",
           "1"
           ])
    print(f'Running merge command: {shlex.join(cmd)}')
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, encoding='utf8')
    print(proc.stdout)
    # delete the temp file
    pathlib.Path(tmp_file_name).unlink()

    # add the audio using a separate command
    # got this from here:
    # https://stackoverflow.com/questions/11779490/how-to-add-a-new-audio-not-mixing-into-a-video-using-ffmpeg
    # tried merging the two command but it didn't immediately work and this doesn't really waste too much time

    if audio_path is not None:
        tmp_output = output_path.parent / (output_path.stem + '.tmp' + output_path.suffix)
        cmd = [
            "ffmpeg",
            "-i",
            str(output_path),
            "-i",
            str(audio_path),
            "-map",
            "0",
            "-map",
            "1:a",
            "-c",
            "copy",
            "-shortest",
            str(tmp_output)
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8')
        print(proc.stdout)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, "yada")
        output_path.unlink()
        tmp_output.rename(str(output_path))

    print(f'Created final video {output_path}')


def parse_args() -> argparse.Namespace:
    ns = argparse.ArgumentParser('Dream Generator')

    ns.add_argument("commands_path", type=pathlib.Path)
    ns.add_argument("--config_path", type=pathlib.Path, default=pathlib.Path("config/tiktok.toml"))
    ns.add_argument("-o", "--output-folder",
                    type=pathlib.Path,
                    default="dream-outputs"
                    )
    ns.add_argument("--force", action="store_true", default=False)
    ns.add_argument("-a", "--audio-file", help="attach audio from the given file to the output video", default=None)

    return ns.parse_args()


if __name__ == '__main__':
    import sys
    sys.exit(main())
