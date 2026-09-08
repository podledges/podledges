"""Throwaway SVG text outliner using existing system FreeType; no installation.
Uses original Geist Mono variable font and exact wght design coordinates.
"""
import ctypes as C
import glob
import html
from pathlib import Path

L=C.c_long; U=C.c_ulong; P=C.c_void_p; I=C.c_int; S=C.c_short
class Generic(C.Structure): _fields_=[('data',P),('finalizer',P)]
class Vector(C.Structure): _fields_=[('x',L),('y',L)]
class BBox(C.Structure): _fields_=[('xmin',L),('ymin',L),('xmax',L),('ymax',L)]
class Metrics(C.Structure): _fields_=[(k,L) for k in ['width','height','horiBearingX','horiBearingY','horiAdvance','vertBearingX','vertBearingY','vertAdvance']]
class Bitmap(C.Structure): _fields_=[('rows',C.c_uint),('width',C.c_uint),('pitch',I),('buffer',P),('num_grays',C.c_ushort),('pixel_mode',C.c_ubyte),('palette_mode',C.c_ubyte),('palette',P)]
class Outline(C.Structure): _fields_=[('n_contours',S),('n_points',S),('points',C.POINTER(Vector)),('tags',P),('contours',C.POINTER(S)),('flags',I)]
class Slot(C.Structure): _fields_=[('library',P),('face',P),('next',P),('glyph_index',C.c_uint),('generic',Generic),('metrics',Metrics),('linearHoriAdvance',L),('linearVertAdvance',L),('advance',Vector),('format',C.c_uint),('bitmap',Bitmap),('bitmap_left',I),('bitmap_top',I),('outline',Outline)]
class Face(C.Structure): _fields_=[('num_faces',L),('face_index',L),('face_flags',L),('style_flags',L),('num_glyphs',L),('family_name',C.c_char_p),('style_name',C.c_char_p),('num_fixed_sizes',I),('available_sizes',P),('num_charmaps',I),('charmaps',P),('generic',Generic),('bbox',BBox),('units_per_EM',C.c_ushort),('ascender',S),('descender',S),('height',S),('max_advance_width',S),('max_advance_height',S),('underline_position',S),('underline_thickness',S),('glyph',C.POINTER(Slot)),('size',P),('charmap',P)]
Move=C.CFUNCTYPE(I,C.POINTER(Vector),P)
Line=Move
Conic=C.CFUNCTYPE(I,C.POINTER(Vector),C.POINTER(Vector),P)
Cubic=C.CFUNCTYPE(I,C.POINTER(Vector),C.POINTER(Vector),C.POINTER(Vector),P)
class Funcs(C.Structure): _fields_=[('move_to',Move),('line_to',Line),('conic_to',Conic),('cubic_to',Cubic),('shift',I),('delta',L)]

def f(n): return str(round(n,4)).rstrip('0').rstrip('.') if '.' in str(round(n,4)) else str(n)

class Font:
    def __init__(self,path):
        libs=glob.glob('/nix/store/*-freetype-*/lib/libfreetype.so.6')
        self.ft=C.CDLL(libs[0] if libs else 'libfreetype.so.6')
        self.lib=P(); assert self.ft.FT_Init_FreeType(C.byref(self.lib))==0
        self.face=C.POINTER(Face)()
        assert self.ft.FT_New_Face(self.lib,str(Path(path).resolve()).encode(),0,C.byref(self.face))==0
        self.em=self.face.contents.units_per_EM
        assert self.ft.FT_Set_Char_Size(self.face,0,self.em*64,72,72)==0
        self.cache={}
    def glyph(self,char,weight):
        key=(char,weight)
        if key in self.cache:return self.cache[key]
        coord=(L*1)(round(weight*65536))
        assert self.ft.FT_Set_Var_Design_Coordinates(self.face,1,coord)==0
        assert self.ft.FT_Load_Char(self.face,ord(char),10)==0
        slot=self.face.contents.glyph.contents
        commands=[]
        def pt(v):return f'{f(v.contents.x/64)} {f(v.contents.y/64)}'
        @Move
        def move(v,_):
            if commands:commands.append('Z')
            commands.append('M'+pt(v));return 0
        @Line
        def line(v,_):commands.append('L'+pt(v));return 0
        @Conic
        def conic(a,b,_):commands.append('Q'+pt(a)+' '+pt(b));return 0
        @Cubic
        def cubic(a,b,c,_):commands.append('C'+pt(a)+' '+pt(b)+' '+pt(c));return 0
        funcs=Funcs(move,line,conic,cubic,0,0)
        assert self.ft.FT_Outline_Decompose(C.byref(slot.outline),C.byref(funcs),None)==0
        if commands:commands.append('Z')
        result=(''.join(commands),slot.metrics.horiAdvance/64)
        self.cache[key]=result
        return result
    def text(self,text,x,y,size,weight=420,fill='#f5f8ff',opacity=1,spacing=0,anchor='start',extra=''):
        items=[self.glyph(c,weight) for c in text]
        s=size/self.em
        width=sum(a*s for _,a in items)+max(0,len(items)-1)*spacing
        if anchor=='end':x-=width
        if anchor=='middle':x-=width/2
        shapes=[]
        for d,a in items:
            if d:shapes.append(f'<path transform="translate({f(x)} {f(y)}) scale({f(s)} -{f(s)})" d="{d}"/>')
            x+=a*s+spacing
        return f'<g data-text="{html.escape(text,quote=True)}" data-font="Geist Mono" data-size="{size}" data-weight="{weight}" fill="{fill}" opacity="{opacity}" {extra}>'+''.join(shapes)+'</g>'

if __name__=='__main__':
    font=Font(Path(__file__).parent/'GeistMono-variable.ttf')
    print('Font:',font.face.contents.family_name.decode(),'units/em:',font.em)
    print('Exact weight changes outline:',font.glyph('4',676)[0]!=font.glyph('4',675)[0])
    print('47 advance:',sum(font.glyph(c,676)[1] for c in '47'))
