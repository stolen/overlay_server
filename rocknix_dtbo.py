#!/usr/bin/env python

# https://pypi.org/project/fdt/
# pip install fdt

import os
import fdt
import math



def prop_default(prop, default):
    try:
        return panel.get_property(prop).value
    except:
        return default

def absfrac(x):
    return abs(x - round(x))

def panel_to_desc(panel, args):
    if 'name' in args:
        g_name = args['name'] + ' '
    else:
        g_name = ''
    comment = args.get('comment')
    acc = []

    delays = [
            prop_default("prepare-delay-ms", 50),
            prop_default("reset-delay-ms", 50),
            prop_default("init-delay-ms", 50),
            prop_default("enable-delay-ms", 50),
            20  # ready -- no such timeout in legacy dtbs
            ]
    delays_str = ','.join(map(str, delays))

    fmt = ['rgb888', 'rgb666', 'rgb666_packed', 'rgb565'] [panel.get_property("dsi,format").value]
    lanes = panel.get_property("dsi,lanes").value
    flags = panel.get_property("dsi,flags").value
    flags |= 0x0400


    timings = panel.get_subnode("display-timings")
    native = timings.get_property("native-mode").value

    # Collect vendor modes
    modes = {}
    orig_def_fps = None
    for m in timings.nodes:
        clock = round(m.get_property("clock-frequency").value/1000)
        hor = [
                m.get_property("hactive").value,
                m.get_property("hfront-porch").value,
                m.get_property("hsync-len").value,
                m.get_property("hback-porch").value,
                ]
        ver = [
                m.get_property("vactive").value,
                m.get_property("vfront-porch").value,
                m.get_property("vsync-len").value,
                m.get_property("vback-porch").value,
                ]
        # Quirk for D28s which has hactive/vactive swapped
        if 'PRs' in args['flags']:
            hor[0] = m.get_property("vactive").value
            ver[0] = m.get_property("hactive").value

        mode = {'clock': clock, 'hor': hor, 'ver': ver}
        if (m.get_property("phandle").value == native):
            mode['default'] = True

        htotal = sum(hor)
        vtotal = sum(ver)
        fps = clock*1000/(htotal*vtotal)

        if fps not in modes:
            modes[fps] = mode
        if (m.get_property("phandle").value == native):
            modes[fps]['default'] = True
            orig_def_fps = fps


    try:
        w = panel.get_property("width-mm").value
        h = panel.get_property("height-mm").value
    except:
        if args.diagonal:
            diag_mm = args.diagonal * 25.4
        else:
            diag_mm = 3.5 * 2.54

        randmode = list(modes.values())[0]
        hactive = randmode['hor'][0]
        vactive = randmode['ver'][0]
        pxdiag = math.sqrt(hactive*hactive + vactive*vactive)
        w = round(diag_mm * hactive/pxdiag)
        h = round(diag_mm * vactive/pxdiag)

    # G size=52,70 delays=2,1,20,120,50,20 format=rgb888 lanes=4 flags=0xe03
    acc += [f"G {g_name}size={w},{h} delays={delays_str} format={fmt} lanes={lanes} flags=0x{flags:x}", ""]

    # Based on vendor modes construct a better set of modes
    # https://tasvideos.org/PlatformFramerates
    # 50, 60        -- generic
    # */1.001       -- NTSC hack with 1001 divisor
    # 50.0070       -- PAL NES  https://www.nesdev.org/wiki/Cycle_reference_chart
    # 60.0988       -- NTSC NES
    # 54.8766       -- src/mame/toaplan/twincobr.cpp
    # 57.5          -- src/mame/kaneko/snowbros.cpp
    # 59.7275       -- https://en.wikipedia.org/wiki/Game_Boy
    # 75.47         -- https://ws.nesdev.org/wiki/Display
    def_fps = 60
    if orig_def_fps:
        def_fps = orig_def_fps
    common_fpss = [50/1.001, 50, 50.0070, 57.5, 59.7275, 60/1.001, 60, 60.0988, 75.47, 90, 120];
    common_fpss = [ fps for fps in common_fpss if fps != orig_def_fps]
    for targetfps in [orig_def_fps] + common_fpss:
        if not targetfps:
            continue
        warn = ""
        # nearest fps to base on
        greaterfps = [fps for fps in modes.keys() if fps >= targetfps]
        if greaterfps == []:
            basefps = max(modes.keys())
            basemode = modes[basefps]
            clock = None
        else:
            # Trust original clock. If real clock differs, maybe make a whitelist or blacklist here
            basefps = min(greaterfps)
            basemode = modes[basefps]
            clock = basemode['clock']
        hor = basemode['hor'].copy()
        ver = basemode['ver'].copy()
        # Assume original totals are minimal for the panel at this clock
        htotal = sum(hor)
        vtotal = sum(ver)
        perfectclock = targetfps*htotal*vtotal/1000
        if not clock:
            warn = "(CAN FAIL) "
            # This may fail, but worth trying. Round up to 10kHz
            clock = math.ceil(perfectclock/10)*10
        elif clock > 1.25*perfectclock:
            # Too much deviation may cause no image
            clock = math.ceil(perfectclock/10)*10

        maxvtotal = round(vtotal*1.25)
        # A little bruteforce to find a best totals for target fps
        # TODO: maybe iterate over some clock values too
        options = [(absfrac(c*1000/targetfps/vt), c, vt)
                for vt in range(vtotal, maxvtotal+1)
                for c in range(clock, round(1.25*perfectclock), 10)
                if ((c*1000/targetfps/vt) >= htotal) and ((c*1000/targetfps/vt) < htotal*1.05) ]
        if options == []:
            acc += [f"# failed to find mode for fps={targetfps:.6f} c={clock} h={htotal} v={vtotal}"]
            continue
        (mindev, newclock, newvtotal) = min(options)
        # construct a new mode with chosen vtotal
        newhtotal = round(newclock*1000/targetfps/newvtotal)
        addhtotal = newhtotal - htotal
        addvtotal = newvtotal - vtotal
        expectedfps = newclock*1000/newvtotal/newhtotal
        hor[2] += addhtotal
        ver[2] += addvtotal
        hor_str = ','.join(map(str, hor))
        ver_str = ','.join(map(str, ver))
        maybe_default = " default=1" if targetfps == def_fps else ""
        maybe_comment = f" # {warn}fps={expectedfps:.6f} (target={targetfps:.6f})" if comment else ""
        acc += [f"M clock={newclock} horizontal={hor_str} vertical={ver_str}{maybe_default}{maybe_comment}"]

    acc += [""]

    iseq0 = panel.get_property("panel-init-sequence")
    if (hasattr(iseq0, 'value')) and (isinstance(iseq0.value, (int))):
        iseq = b''.join(map(lambda w : w.to_bytes(4, "big"), list(iseq0)))
    else:
        iseq = bytearray(iseq0)

    while iseq:
        cmd = iseq[0]
        wait = iseq[1]
        datalen = iseq[2]
        iseq = iseq[3:]

        data = iseq[0:datalen]
        iseq = iseq[datalen:]

        maybe_wait = f" wait={wait}" if (wait) else ""
        maybe_comment = f" # orig_cmd=0x{cmd:x}" if comment else ""
        acc += [f"I seq={data.hex()}{maybe_wait}{maybe_comment}"]

    return acc

def resolve_phandle(dt, phandle):
    paths = [os.path.join(p.parent.path, p.parent.name)
             for p in dt.search('phandle', fdt.ItemType.PROP_WORDS)
             if p.value == phandle]
    return paths[0]

def add_overlay(overlay, path):
    for f in range(100):
        nodename = 'fragment@' + str(f)
        if overlay.exist_node(nodename):
            pass
        else:
            fragnode = fdt.Node(nodename)
            if path[0] == '&':
                fragnode.set_property('target', 0xffffffff)
                overlay.set_property(path[1:], '/'+nodename+':target:0', path='/__fixups__')
            else:
                fragnode.set_property('target-path', path)
            overlay.add_item(fragnode)
            ovlnode = fdt.Node('__overlay__')
            fragnode.append(ovlnode)
            return ovlnode


def make_dtbo(dtb_data, args):
    dt = fdt.parse_dtb(dtb_data)
    symbols = dt.get_node('__symbols__')

    dsipath = symbols.get_property('dsi').value
    # panelpath is /dsi@ff450000/panel@0 on rk3326 and /dsi@fe060000/panel@0 on rk3566
    panelpath = dsipath + '/panel@0'
    panel = dt.get_node(panelpath)
    pdesc = panel_to_desc(panel, args)

    # remove empty lines as pyfdt does not like them
    pdesc = [ l for l in pdesc if l != '']

    # create an overlay tree
    overlay = fdt.FDT()
    overlay.header.version = 17

    panel_ovl = add_overlay(overlay, panelpath)
    panel_ovl.set_property('compatible', 'rocknix,generic-dsi')
    panel_ovl.set_property('panel_description', pdesc)

    # If needed, invert right stick
    if 'RSi' in args['flags']:
        rsi_ovl = add_overlay(overlay, '&joypad')
        rsi_ovl.set_property('invert-absrx', 1)
        rsi_ovl.set_property('invert-absry', 1)
        args['logger'].info(f"invert right stick on {rsi_ovl.path}")

    if dt.exist_node('/rk817-sound'):
        snd = dt.get_node('/rk817-sound')
        # fetch raw   hp-det-gpio = <0x6f 0x16 0x00>;
        hpdet = snd.get_property('hp-det-gpio').data
        # resolve <0x6f> into '/pinctrl/gpio2@ff260000'
        hpdet_gpio_path = resolve_phandle(dt, hpdet[0])
        # find symbol 'gpio2' for path '/pinctrl/gpio2@ff260000'
        gpiosyms = [p.name for p in symbols.props if p.value == hpdet_gpio_path]
        if gpiosyms:
            # on success, add overlay
            hpdet_ovl = add_overlay(overlay, '/rk817-sound')
            hpdet_ovl.set_property('simple-audio-card,hp-det-gpio', [0xffffffff, hpdet[1], hpdet[2]])
            overlay.set_property(gpiosyms[0], hpdet_ovl.path+'/__overlay__:simple-audio-card,hp-det-gpio:0', path='/__fixups__')
            args['logger'].info(f"hp-det-gpio {gpiosyms[0]} on {hpdet_ovl.path}")

    # Move fixups to the very end (if any)
    if overlay.exist_node('__fixups__'):
        fixups = overlay.get_node('__fixups__')
        overlay.remove_node('__fixups__')
        overlay.add_item(fixups)

    # send the overlay to output
    return overlay.to_dtb()
