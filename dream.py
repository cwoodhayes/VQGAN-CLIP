import argparse
import subprocess
import pathlib
import typing
from tempfile import NamedTemporaryFile

OUTPUT_IMAGE_NAME = 'output.png'
OUTPUT_VIDEO_NAME = 'output.mp4'
OUTPUT_VIDEO_SUFFIX = '.mp4'


def main() -> int:
    ns = parse_args()

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

    with open(ns.commands_path, 'r') as commands_fp:
        full_cmd = f"python {ns.generate_script_path} -vid "
        for idx, line in enumerate(commands_fp):
            line = line.strip()
            if line.startswith('#') or len(line) == 0:
                continue
            full_cmd += f' {line}'
            if line.endswith('\\'):
                full_cmd = full_cmd[:-1]
                continue

            # and run that thang, piping stdout out
            ret = run_cmd(full_cmd)

            if ret != 0:
                print(f'this returned error {ret}: {full_cmd}')
                return 2

            # now grab the outputs and stick them in our output folder.
            img = pathlib.Path(OUTPUT_IMAGE_NAME)
            vid = pathlib.Path(OUTPUT_VIDEO_NAME)

            img.rename(output_folder / f"{output_name}{idx}{img.suffix}")
            vid.rename(output_folder / f"{output_name}{idx}{OUTPUT_VIDEO_SUFFIX}")
            print(f"Generated {img} and {vid}")
            # the next video should start from the last frame of this one
            full_cmd = f"python {ns.generate_script_path} -vid -ii {img}"

    # make the final video by concatenating all previous
    clips = output_folder.glob(f"*{OUTPUT_VIDEO_SUFFIX}")

    merge_videos(clips, output_folder / f"{output_name}{OUTPUT_VIDEO_SUFFIX}")

    return 0


def merge_videos(video_list: typing.Iterable[pathlib.Path], output_path: pathlib.Path) -> None:
    """
    :returns: path to merged video
    """
    # let's use ffmpeg directly. To do so, we need to make a temporary input file of all the files to merge
    with NamedTemporaryFile('w', delete=False) as input_list_file:
        tmp_file_name = input_list_file.name
        lines = [f"file {path.resolve()}\n" for path in video_list]
        input_list_file.writelines(lines)

    # merge the video files
    cmd = ["ffmpeg",
           "-f",
           "concat",
           "-safe",
           "0",
           "-i",
           tmp_file_name,
           "-c",
           "copy",
           str(output_path)
           ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    print(proc.stdout)
    # delete the temp file
    pathlib.Path(tmp_file_name).unlink()

    print(f'Created final video {output_path}')


def run_cmd(cmd_string: str) -> int:
    print('running command: {}'.format(cmd_string))
    # args = shlex.split(full_cmd)
    process = subprocess.Popen(
        shell=True,
        args=cmd_string,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        bufsize=1,
        encoding='utf8'
    )

    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
    rc = process.poll()
    return rc


def parse_args() -> argparse.Namespace:
    ns = argparse.ArgumentParser('Dream Generator')

    ns.add_argument("commands_path", type=pathlib.Path)
    ns.add_argument("--generate-script-path", type=pathlib.Path, default=pathlib.Path("generate.py"))
    ns.add_argument("-o", "--output-folder",
                    type=pathlib.Path,
                    default="dream-outputs"
                    )
    ns.add_argument("--force", action="store_true", default=False)

    return ns.parse_args()


if __name__ == '__main__':
    import sys
    sys.exit(main())
