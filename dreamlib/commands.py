from __future__ import annotations

import pathlib
import re
import subprocess
import typing
import dataclasses

__THIS_FILE_PATH = pathlib.Path(__file__).absolute()
GENERATE_SCRIPT_PATH = __THIS_FILE_PATH.parents[1] / "generate.py"


class InvalidCommandStringError(ValueError):
    pass


@dataclasses.dataclass
class GenerateVideoCommand:
    """
    represents a single command to the vqgan-clip generator
    that we are scripting around
    """
    CMD_BASE: typing.ClassVar[str] = f"python {GENERATE_SCRIPT_PATH} -vid"
    INPUT_LINE_RE: typing.ClassVar[re.Pattern] = re.compile(r"(?P<video_len>\d+)(?P<cmd>.*)")

    cmd_string: str
    video_len_s: int

    initial_frame_path: typing.Optional[pathlib.Path] = None
    dimensions: typing.Tuple[int, int] = (380, 380)
    frame_rate: int = 30
    # save every n'th iteration as a frame of the video
    save_every_freq: int = 3

    @classmethod
    def from_input_line(cls, line: str) -> GenerateVideoCommand:
        """
        creates a command instance from the input format we use in our scripts
        """
        match = cls.INPUT_LINE_RE.match(line)
        if match:
            return GenerateVideoCommand(
                cmd_string=match.group("cmd"),
                video_len_s=int(match.group("video_len"))
            )
        raise InvalidCommandStringError

    def __post_init__(self):
        self.cmd_string = self.cmd_string.strip()

    def __str__(self) -> str:
        string = self.CMD_BASE + " " + self.cmd_string.strip()

        # determine number of iterations to run based on given params
        n_iterations = self.frame_rate * self.video_len_s * self.save_every_freq
        string += f" -i {n_iterations}"
        string += f" -se {self.save_every_freq}"

        string += f" -vl {self.video_len_s}"

        if self.initial_frame_path:
            string += f" -ii {self.initial_frame_path}"

        string += f" -s {self.dimensions[0]} {self.dimensions[1]}"

        return string

    def add_options(self, cmd_string: str) -> None:
        """
        Adds an additional set of options to this command

        :param cmd_string:
        """
        cmd_string = cmd_string.strip()
        if cmd_string:
            self.cmd_string += " " + cmd_string

    def add_options_from_config(self, config: dict) -> None:
        """
        add additional options from a config dictionary

        :param config:
        :return:
        """
        self.frame_rate = int(config['frame-rate'])
        self.dimensions = (int(config['width']), int(config['height']))
        self.save_every_freq = int(config['save-every-freq'])
        if 'extra-options' in config:
            self.add_options(config['extra-options'])


def run_cmd(cmd: GenerateVideoCommand) -> int:
    """
    Run the script for the given command as a subprocess, outputting to stdout as we go

    :param cmd: cmd to run
    :return: retcode from subprocess
    """
    return run_cmd_string(str(cmd))


def run_cmd_string(cmd_string: str) -> int:
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


