from multiprocessing import Process, Pipe
from tqdm.auto import tqdm
import sys

class PBar(Process):
    def __init__(self, pipe: Pipe, has_bar, stdout: str):
        self.pipe: Pipe = pipe
        self.stdout = stdout
        # this is a shared obj using mp Manager
        # using mp manager to be able to change this value
        # here and and have it changed in the Output.py
        Process.__init__(self)

        self.has_pbar = has_bar
        if not self.unknown_total_flows():
            self.has_pbar.value = True



    def terminate(self):
        #TODO store the pid of this process somewhere
        # and handle it's termination'
        ...

    def print(self, msg: dict):
        """
        prints using tqdm in order to avoid conflict with the pbar
        """
        tqdm.write(msg['txt'])


    def update_stats(self, msg: dict):
        """writes the stats sent in the msg as a pbar postfix"""
        self.progress_bar.set_postfix_str(
            msg['stats'],
            refresh=True
        )

    def run(self):
        while True and self.has_pbar.value:
            msg: dict = self.pipe.recv()
            event: str = msg['event']
            if event == "init":
                self.init(msg)

            if event == "update_bar":
                self.update_bar()

            if event == "update_stats":
                self.update_stats(msg)


            if event == "terminate":
                self.terminate()

            if event == "print":
                # let tqdm do th eprinting to avoid conflicts with the pbar
                self.print(msg)
