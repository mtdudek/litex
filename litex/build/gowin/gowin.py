#
# This file is part of LiteX.
#
# Copyright (c) 2020 Pepijn de Vos <pepijndevos@gmail.com>
# Copyright (c) 2015-2018 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import os
import math
import subprocess
from shutil import which

from migen.fhdl.structure import _Fragment

from litex.build.generic_platform import *
from litex.build import tools

# Constraints (.cst and .tcl) ----------------------------------------------------------------------

def _build_cst(named_sc, named_pc):
    cst = []

    flat_sc = []
    for name, pins, other, resource in named_sc:
        if len(pins) > 1:
            for i, p in enumerate(pins):
                flat_sc.append((f"{name}[{i}]", p, other))
        else:
            flat_sc.append((name, pins[0], other))

    for name, pin, other in flat_sc:
        if pin != "X":
            cst.append(f"IO_LOC \"{name}\" {pin};")

        for c in other:
            if isinstance(c, IOStandard):
                cst.append(f"IO_PORT \"{name}\" IO_TYPE={c.name};")
            elif isinstance(c, Misc):
                cst.append(f"IO_PORT \"{name}\" {c.misc};")

    if named_pc:
        cst.extend(named_pc)

    with open("top.cst", "w") as f:
        f.write("\n".join(cst))

def _build_sdc(clocks, vns):
    sdc = []
    for clk, period in sorted(clocks.items(), key=lambda x: x[0].duid):
        sdc.append(f"create_clock -name {vns.get_name(clk)} -period {str(period)} [get_ports {{{vns.get_name(clk)}}}]")
    with open("top.sdc", "w") as f:
        f.write("\n".join(sdc))

# Script -------------------------------------------------------------------------------------------

def _build_tcl(name, partnumber, files, options):
    tcl = []

    # Set Device.
    tcl.append(f"set_device -name {name} {partnumber}")

    # Add IOs Constraints.
    tcl.append("add_file top.cst")

    # Add Timings Constraints.
    tcl.append("add_file top.sdc")

    # Add Sources.
    for f, typ, lib in files:
        tcl.append(f"add_file {f}")

    # Set Options.
    for opt, val in options.items():
        tcl.append(f"set_option -{opt} {val}")

    # Run.
    tcl.append("run all")

    # Generate .tcl.
    with open("run.tcl", "w") as f:
        f.write("\n".join(tcl))

# GowinToolchain -----------------------------------------------------------------------------------

class GowinToolchain:
    attr_translate = {}

    def __init__(self):
        self.options = {}
        self.clocks  = dict()

    def build(self, platform, fragment,
        build_dir  = "build",
        build_name = "top",
        run        = True,
        **kwargs):

        # Create build directory.
        cwd = os.getcwd()
        os.makedirs(build_dir, exist_ok=True)
        os.chdir(build_dir)

        # Finalize design
        if not isinstance(fragment, _Fragment):
            fragment = fragment.get_fragment()
        platform.finalize(fragment)

        # Generate verilog
        v_output = platform.get_verilog(fragment, name=build_name, **kwargs)
        named_sc, named_pc = platform.resolve_signals(v_output.ns)
        v_file = build_name + ".v"
        v_output.write(v_file)
        platform.add_source(v_file)

        if platform.verilog_include_paths:
            self.options["include_path"] = "{" + ";".join(platform.verilog_include_paths) + "}"

        # Generate constraints file.
        # IOs (.cst).
        _build_cst(
            named_sc = named_sc,
            named_pc = named_pc
        )

        # Timings (.sdc)
        _build_sdc(
            clocks  = self.clocks,
            vns     = v_output.ns
        )

        # Generate build script (.tcl)
        script = _build_tcl(
            name       = platform.devicename,
            partnumber = platform.device,
            files      = platform.sources,
            options    = self.options)

        # Run
        if run:
            if which("gw_sh") is None:
                msg = "Unable to find Gowin toolchain, please:\n"
                msg += "- Add Gowin toolchain to your $PATH."
                raise OSError(msg)

            if subprocess.call(["gw_sh", "run.tcl"]) != 0:
                raise OSError("Error occured during Gowin's script execution.")

        os.chdir(cwd)

        return v_output.ns

    def add_period_constraint(self, platform, clk, period):
        clk.attr.add("keep")
        period = math.floor(period*1e3)/1e3 # round to lowest picosecond
        if clk in self.clocks:
            if period != self.clocks[clk]:
                raise ValueError("Clock already constrained to {:.2f}ns, new constraint to {:.2f}ns"
                    .format(self.clocks[clk], period))
        self.clocks[clk] = period
