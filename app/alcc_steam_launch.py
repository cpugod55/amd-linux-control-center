"""Pure Steam launch-options KeyValues helpers for AMD Linux Control Center.

This module owns parsing, validation, reading, and text patching of Steam's
localconfig.vdf launch options. It performs no file writes, backups, process
control, UI work, or persistence orchestration.
"""

import pathlib
import re


def vdf_unescape(value):
    return value.replace(r'\"','"').replace(r'\\','\\')


def vdf_escape(value):
    return str(value).replace("\\","\\\\").replace('"','\\"')


def vdf_tokenize(text):
    toks=[]
    pat=re.compile(r'"((?:\\.|[^"\\])*)"|([{}])',re.S)
    for m in pat.finditer(text):
        if m.group(2):
            toks.append({"kind":m.group(2),"value":m.group(2),"start":m.start(),"end":m.end()})
        else:
            toks.append({"kind":"str","value":vdf_unescape(m.group(1)),"raw_start":m.start(1),"raw_end":m.end(1),"start":m.start(),"end":m.end()})
    return toks


def vdf_nodes(text):
    toks=vdf_tokenize(text); nodes=[]; n=len(toks)
    def parse_block(open_i,path,key=None):
        node={"path":tuple(path),"key":key,"open_i":open_i,"close_i":None,"pairs":{}}; nodes.append(node); i=open_i+1
        while i<n:
            t=toks[i]
            if t["kind"]=="}": node["close_i"]=i; return i+1
            if t["kind"]!="str": i+=1; continue
            k=t["value"]
            if i+1<n and toks[i+1]["kind"]=="{": i=parse_block(i+1,path+[k],k); continue
            if i+1<n and toks[i+1]["kind"]=="str": node["pairs"].setdefault(k.lower(),[]).append((i,i+1)); i+=2; continue
            i+=1
        return i
    i=0
    while i+1<n:
        if toks[i]["kind"]=="str" and toks[i+1]["kind"]=="{": i=parse_block(i+1,[toks[i]["value"]],toks[i]["value"])
        else: i+=1
    return toks,nodes


def vdf_find_node(text,path):
    toks,nodes=vdf_nodes(text); low=tuple(str(x).lower() for x in path)
    for node in nodes:
        if tuple(str(x).lower() for x in node["path"])==low: return toks,node
    return toks,None


def steam_app_path(appid):
    return ("UserLocalConfigStore","Software","Valve","Steam","apps",str(appid))


def read_launch_options_from_localconfig(path,appid):
    try: text=pathlib.Path(path).read_text(encoding="utf-8",errors="ignore")
    except Exception: return ""
    toks,node=vdf_find_node(text,steam_app_path(appid))
    if not node: return ""
    pairs=node["pairs"].get("launchoptions",[])
    if not pairs: return ""
    _,vi=pairs[-1]; return toks[vi]["value"]


def indent_for_block(text,toks,node):
    open_tok=toks[node["open_i"]]; line_start=text.rfind("\n",0,open_tok["start"])+1; before=text[line_start:open_tok["start"]]
    return re.match(r"[ \t]*",before).group(0)


def patch_steam_launch_options_text(text,appid,launch_options):
    toks,node=vdf_find_node(text,steam_app_path(appid)); escaped=vdf_escape(launch_options)
    if node:
        pairs=node["pairs"].get("launchoptions",[])
        if pairs:
            _,vi=pairs[-1]; vt=toks[vi]
            return text[:vt["raw_start"]]+escaped+text[vt["raw_end"]:]
        close=toks[node["close_i"]]; base=indent_for_block(text,toks,node); child_indent=base+"\t"; insertion=f'{child_indent}"LaunchOptions"\t\t"{escaped}"\n'
        return text[:close["start"]]+insertion+text[close["start"]:]
    toks,apps=vdf_find_node(text,("UserLocalConfigStore","Software","Valve","Steam","apps"))
    if not apps: raise RuntimeError("Steam's apps section could not be found in localconfig.vdf. Nothing was changed.")
    close=toks[apps["close_i"]]; base=indent_for_block(text,toks,apps); child=base+"\t"; grand=child+"\t"
    insertion=f'{child}"{appid}"\n{child}'+'{\n'+f'{grand}"LaunchOptions"\t\t"{escaped}"\n{child}'+'}\n'
    return text[:close["start"]]+insertion+text[close["start"]:]


def validate_steam_localconfig_text(text):
    if not isinstance(text,str) or not text.strip(): raise RuntimeError("Steam localconfig.vdf is empty")
    toks,nodes=vdf_nodes(text); depth=0
    for tok in toks:
        if tok["kind"]=="{": depth+=1
        elif tok["kind"]=="}":
            depth-=1
            if depth<0: raise RuntimeError("Steam localconfig.vdf has unbalanced braces")
    if depth or any(node.get("close_i") is None for node in nodes): raise RuntimeError("Steam localconfig.vdf has an incomplete block")
    _,apps=vdf_find_node(text,("UserLocalConfigStore","Software","Valve","Steam","apps"))
    if not apps: raise RuntimeError("Steam localconfig.vdf has no valid apps section")
    return True


def normalize_launch_options(value):
    return str(value or "").strip()
