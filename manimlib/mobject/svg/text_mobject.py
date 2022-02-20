import hashlib
import os
import re
import io
import typing
import xml.etree.ElementTree as ET
import functools
import pygments
import pygments.lexers
import pygments.styles

from contextlib import contextmanager
from pathlib import Path

import manimpango
from manimlib.logger import log
from manimlib.constants import *
from manimlib.mobject.geometry import Dot
from manimlib.mobject.svg.svg_mobject import SVGMobject
from manimlib.mobject.types.vectorized_mobject import VMobject
from manimlib.mobject.types.vectorized_mobject import VGroup
from manimlib.utils.config_ops import digest_config
from manimlib.utils.customization import get_customization
from manimlib.utils.directories import get_downloads_dir, get_text_dir
from manimpango import PangoUtils, TextSetting, MarkupUtils

TEXT_MOB_SCALE_FACTOR = 0.0076
DEFAULT_LINE_SPACING_SCALE = 0.6


class Text(SVGMobject):
    CONFIG = {
        # Mobject
        "color": WHITE,
        "height": None,
        "stroke_width": 0,
        # Text
        "lsh": None,
        "size": None,
        "font_size": 48,
        "font": None,
        "gradient": None,
        "slant": NORMAL,
        "weight": NORMAL,
        "t2c": {},
        "t2f": {},
        "t2g": {},
        "t2s": {},
        "t2w": {},
        "disable_ligatures": True,
    }

    def __init__(self, text, **kwargs):
        self.full2short(kwargs)
        digest_config(self, kwargs)
        self.text = text
        if self.size:
            log.warning(
                "`self.size` has been deprecated and will "
                "be removed in future.",
            )
            self.font_size = self.size
        self.lsh = self.font_size * (1 + (
            self.lsh or DEFAULT_LINE_SPACING_SCALE
        ))
        if self.font is None:
            self.font = get_customization()["style"]["font"]
        file_name = self.text2svg()
        #self.remove_last_M(file_name)
        #self.remove_empty_path(file_name)
        super().__init__(file_name, **kwargs)
        self.remove_empty_submobs()   # TODO: move into generate_mobject
        self.apply_space_chars()   # TODO: move into generate_mobject

        self.set_color_by_t2c(self.t2c)
        if self.gradient:
            self.set_color_by_gradient(*self.gradient)
        self.set_color_by_t2g(self.t2g)

        # anti-aliasing
        if self.height is None:
            self.scale(TEXT_MOB_SCALE_FACTOR)

    #def remove_empty_path(self, file_name):
    #    with open(file_name, 'r') as fpr:
    #        content = fpr.read()
    #    content = re.sub(r'<path .*?d=""/>', '', content)
    #    with open(file_name, 'w') as fpw:
    #        fpw.write(content)

    #def remove_last_M(self, file_name):
    #    """Remove element from the SVG file in order to allow comparison."""
    #    with open(file_name, "r") as fpr:
    #        content = fpr.read()
    #    content = re.sub(r'Z M [^A-Za-z]*? "\/>', 'Z "/>', content)
    #    with open(file_name, "w") as fpw:
    #        fpw.write(content)

    def remove_empty_submobs(self):  # TODO
        self.set_submobjects(list(filter(
            lambda submob: submob.has_points(),
            self.submobjects
        )))

    def apply_space_chars(self):
        # Align every character with a submobject
        submobs = self.submobjects.copy()
        for wsp_match_obj in re.finditer(r"\s", self.text):
            char_index = wsp_match_obj.start()
            space = Dot(radius=0, fill_opacity=0, stroke_opacity=0)
            space.move_to(submobs[max(char_index - 1, 0)].get_center())
            submobs.insert(char_index, space)
        self.set_submobjects(submobs)

    def set_color_by_t2c(self, t2c):
        for word, color in t2c.items():
            for start, end in self.find_indexes(word):
                self[start:end].set_color(color)

    def set_color_by_t2g(self, t2g):
        for word, gradient in t2g.items():
            for start, end in self.find_indexes(word):
                self[start:end].set_color_by_gradient(*gradient)

    def find_indexes(self, tuple_or_word):
        if isinstance(tuple_or_word, tuple):
            return [tuple_or_word]

        # TODO: needed?
        m = re.match(r'\[([0-9\-]{0,}):([0-9\-]{0,})\]', tuple_or_word)
        if m:
            start = int(m.group(1)) if m.group(1) != '' else 0
            end = int(m.group(2)) if m.group(2) != '' else len(self.text)
            start = len(self.text) + start if start < 0 else start
            end = len(self.text) + end if end < 0 else end
            return [(start, end)]

        return [
            match_obj.span()
            for match_obj in re.finditer(re.escape(tuple_or_word), self.text)
        ]

    def get_parts_by_text(self, word):
        return VGroup(*(
            self[i:j]
            for i, j in self.find_indexes(word)
        ))

    def get_part_by_text(self, word):
        parts = self.get_parts_by_text(word)
        if len(parts) > 0:
            return parts[0]
        else:
            return None

    def full2short(self, config):
        for kwargs in [config, self.CONFIG]:
            if kwargs.__contains__('line_spacing_height'):
                kwargs['lsh'] = kwargs.pop('line_spacing_height')
            if kwargs.__contains__('text2color'):
                kwargs['t2c'] = kwargs.pop('text2color')
            if kwargs.__contains__('text2font'):
                kwargs['t2f'] = kwargs.pop('text2font')
            if kwargs.__contains__('text2gradient'):
                kwargs['t2g'] = kwargs.pop('text2gradient')
            if kwargs.__contains__('text2slant'):
                kwargs['t2s'] = kwargs.pop('text2slant')
            if kwargs.__contains__('text2weight'):
                kwargs['t2w'] = kwargs.pop('text2weight')

    def text2hash(self):  # TODO
        settings = self.font + self.slant + self.weight
        settings += str(self.t2f) + str(self.t2s) + str(self.t2w)
        settings += str(self.lsh) + str(self.font_size)
        id_str = self.text + settings
        hasher = hashlib.sha256()
        hasher.update(id_str.encode())
        return hasher.hexdigest()[:16]

    def get_t2x_components(self, t2x_dict):
        """
        Convert to non-overlapping items
        """
        result = []
        for key, value in t2x_dict.items():
            for text_span in self.find_indexes(key):
                if text_span[0] >= text_span[1]:
                    continue
                new_result = [(text_span, value)]
                for s, v in result:
                    if text_span[1] <= s[0] or s[1] <= text_span[0]:
                        new_result.append((s, v))
                        continue
                    if s[0] < text_span[0]:
                        new_result.append(((s[0], text_span[0]), v))
                    if text_span[1] < s[1]:
                        new_result.append(((text_span[1], s[1]), v))
                result = new_result
        return sorted(result)

    def merge_t2x_items(self, *t2x_dicts):
        result = []
        def append_item(t2x_items, current_index):
            next_index = min(item[0][1] for item in t2x_items)
            result.append(((current_index, next_index), tuple(item[1] for item in t2x_items)))
            return next_index

        t2x_item_generators = [
            iter(self.get_t2x_components(t2x_dict))
            for t2x_dict in t2x_dicts
        ]
        t2x_items = [next(gen) for gen in t2x_item_generators]
        current_index = append_item(t2x_items, 0)
        text_len = len(self.text)
        while current_index != text_len:
            for i, gen in enumerate(t2x_item_generators):
                if t2x_items[i][0][1] == current_index:
                    t2x_items[i] = next(gen)
            current_index = append_item(t2x_items, current_index)
        return result

    def text2settings(self):
        # Substrings specified in t2f, t2s, t2w may occupy each other
        full_span = (0, len(self.text))
        t2f = {full_span: self.font, **self.t2f}
        t2s = {full_span: self.slant, **self.t2s}
        t2w = {full_span: self.weight, **self.t2w}
        t2l = {full_span: self.text.count("\n"), **{
            match_obj.span(): line_num
            for line_num, match_obj in enumerate(re.finditer(r".*\n", self.text))
        }}
        setting_items = self.merge_t2x_items(
            t2f, t2s, t2w, t2l
        )
        settings = [
            TextSetting(*text_span, *values)
            for text_span, values in setting_items
        ]
        return settings

    def text2svg(self):
        # anti-aliasing
        size = self.font_size
        lsh = self.lsh

        dir_name = get_text_dir()
        hash_name = self.text2hash()
        file_name = os.path.join(dir_name, hash_name) + '.svg'
        #if os.path.exists(file_name):  # TODO: recover
        #    return file_name
        settings = self.text2settings()
        width = DEFAULT_PIXEL_WIDTH
        height = DEFAULT_PIXEL_HEIGHT
        disable_liga = self.disable_ligatures
        return manimpango.text2svg(
            settings,
            size,
            lsh,
            disable_liga,
            file_name,
            START_X,
            START_Y,
            width,
            height,
            self.text,
        )


class MarkupText(SVGMobject):
    CONFIG = {
        # Mobject
        "color": WHITE,
        "height": None,
        # Text
        "font": '',
        "font_size": 48,
        "lsh": None,
        "justify": False,
        "slant": NORMAL,
        "weight": NORMAL,
        "tab_width": 4,
        "gradient": None,
        "disable_ligatures": True,
    }

    def __init__(self, text, **config):
        digest_config(self, config)
        self.text = f'<span>{text}</span>'
        self.original_text = self.text
        self.text_for_parsing = self.text
        text_without_tabs = text
        if "\t" in text:
            text_without_tabs = text.replace("\t", " " * self.tab_width)
        try:
            colormap = self.extract_color_tags()
            gradientmap = self.extract_gradient_tags()
        except ET.ParseError:
            # let pango handle that error
            pass
        validate_error = MarkupUtils.validate(self.text)
        if validate_error:
            raise ValueError(validate_error)
        file_name = self.text2svg()
        PangoUtils.remove_last_M(file_name)
        super().__init__(
            file_name,
            **config,
        )
        self.chars = self.get_group_class()(*self.submobjects)
        self.text = text_without_tabs.replace(" ", "").replace("\n", "")
        if self.gradient:
            self.set_color_by_gradient(*self.gradient)
        for col in colormap:
            self.chars[
                col["start"]
                - col["start_offset"] : col["end"]
                - col["start_offset"]
                - col["end_offset"]
            ].set_color(self._parse_color(col["color"]))
        for grad in gradientmap:
            self.chars[
                grad["start"]
                - grad["start_offset"] : grad["end"]
                - grad["start_offset"]
                - grad["end_offset"]
            ].set_color_by_gradient(
                *(self._parse_color(grad["from"]), self._parse_color(grad["to"]))
            )
        # anti-aliasing
        if self.height is None:
            self.scale(TEXT_MOB_SCALE_FACTOR)

    def text2hash(self):
        """Generates ``sha256`` hash for file name."""
        settings = (
            "MARKUPPANGO" + self.font + self.slant + self.weight + self.color
        )  # to differentiate from classical Pango Text
        settings += str(self.lsh) + str(self.font_size)
        settings += str(self.disable_ligatures)
        settings += str(self.justify)
        id_str = self.text + settings
        hasher = hashlib.sha256()
        hasher.update(id_str.encode())
        return hasher.hexdigest()[:16]
    
    def text2svg(self):
        """Convert the text to SVG using Pango."""
        size = self.font_size
        dir_name = get_text_dir()
        disable_liga = self.disable_ligatures
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        hash_name = self.text2hash()
        file_name = os.path.join(dir_name, hash_name) + ".svg"
        if os.path.exists(file_name):
            return file_name

        extra_kwargs = {}
        extra_kwargs['justify'] = self.justify
        extra_kwargs['pango_width'] = DEFAULT_PIXEL_WIDTH - 100
        if self.lsh:
            extra_kwargs['line_spacing']=self.lsh
        return MarkupUtils.text2svg(
            f'<span foreground="{self.color}">{self.text}</span>',
            self.font,
            self.slant,
            self.weight,
            size,
            0, # empty parameter
            disable_liga,
            file_name,
            START_X,
            START_Y,
            DEFAULT_PIXEL_WIDTH,  # width
            DEFAULT_PIXEL_HEIGHT,  # height
            **extra_kwargs
        )

    def _parse_color(self, col):
        """Parse color given in ``<color>`` or ``<gradient>`` tags."""
        if re.match("#[0-9a-f]{6}", col):
            return col
        else:
            return globals()[col.upper()] # this is hacky

    @functools.lru_cache(10)
    def get_text_from_markup(self, element=None):
        if not element:
            element = ET.fromstring(self.text_for_parsing)
        final_text = ''
        for i in element.itertext():
            final_text += i
        return final_text

    def extract_color_tags(self, text=None, colormap = None):
        """Used to determine which parts (if any) of the string should be formatted
        with a custom color.
        Removes the ``<color>`` tag, as it is not part of Pango's markup and would cause an error.
        Note: Using the ``<color>`` tags is deprecated. As soon as the legacy syntax is gone, this function
        will be removed.
        """
        if not text:
            text = self.text_for_parsing
        if not colormap:
            colormap = list()
        elements = ET.fromstring(text)
        text_from_markup = self.get_text_from_markup()
        final_xml = ET.fromstring(f'<span>{elements.text if elements.text else ""}</span>')
        def get_color_map(elements):
            for element in elements:
                if element.tag == 'color':
                    element_text = self.get_text_from_markup(element)
                    start = text_from_markup.find(element_text)
                    end = start + len(element_text)
                    offsets = element.get('offset').split(",") if element.get('offset') else [0]
                    start_offset = int(offsets[0]) if offsets[0] else 0
                    end_offset = int(offsets[1]) if len(offsets) == 2 and offsets[1] else 0
                    colormap.append(
                        {
                            "start": start,
                            "end": end,
                            "color": element.get('col'),
                            "start_offset": start_offset,
                            "end_offset": end_offset,
                        }
                    )
                    
                    _elements_list = list(element.iter())
                    if len(_elements_list) <= 1:
                        final_xml.append(ET.fromstring(f'<span>{element.text if element.text else ""}</span>'))
                    else:
                        final_xml.append(_elements_list[-1])
                else:
                    if len(list(element.iter())) == 1:
                        final_xml.append(element)
                    else:
                        get_color_map(element)
        get_color_map(elements)
        with io.BytesIO() as f:
            tree = ET.ElementTree()  
            tree._setroot(final_xml)
            tree.write(f)
            self.text = f.getvalue().decode()
        self.text_for_parsing = self.text # gradients will use it
        return colormap

    def extract_gradient_tags(self, text=None,gradientmap=None):
        """Used to determine which parts (if any) of the string should be formatted
        with a gradient.
        Removes the ``<gradient>`` tag, as it is not part of Pango's markup and would cause an error.
        """
        if not text:
            text = self.text_for_parsing
        if not gradientmap:
            gradientmap = list()

        elements = ET.fromstring(text)
        text_from_markup = self.get_text_from_markup()
        final_xml = ET.fromstring(f'<span>{elements.text if elements.text else ""}</span>')
        def get_gradient_map(elements):
            for element in elements:
                if element.tag == 'gradient':
                    element_text = self.get_text_from_markup(element)
                    start = text_from_markup.find(element_text)
                    end = start + len(element_text)
                    offsets = element.get('offset').split(",") if element.get('offset') else [0]
                    start_offset = int(offsets[0]) if offsets[0] else 0
                    end_offset = int(offsets[1]) if len(offsets) == 2 and offsets[1] else 0
                    gradientmap.append(
                        {
                            "start": start,
                            "end": end,
                            "from": element.get('from'),
                            "to": element.get('to'),
                            "start_offset": start_offset,
                            "end_offset": end_offset,
                        }
                    )
                    _elements_list = list(element.iter())
                    if len(_elements_list) == 1:
                        final_xml.append(ET.fromstring(f'<span>{element.text if element.text else ""}</span>'))
                    else:
                        final_xml.append(_elements_list[-1])
                else:
                    if len(list(element.iter())) == 1:
                        final_xml.append(element)
                    else:
                        get_gradient_map(element)
        get_gradient_map(elements)
        with io.BytesIO() as f:
            tree = ET.ElementTree()  
            tree._setroot(final_xml)
            tree.write(f)
            self.text = f.getvalue().decode()

        return gradientmap

    def __repr__(self):
        return f"MarkupText({repr(self.original_text)})"


class Code(Text):
    CONFIG = {
        "font": "Consolas",
        "font_size": 24,
        "lsh": 1.0,
        "language": "python",
        # Visit https://pygments.org/demo/ to have a preview of more styles.
        "code_style": "monokai",
        # If not None, then each character will cover a space of equal width.
        "char_width": None
    }

    def __init__(self, code, **kwargs):
        self.full2short(kwargs)
        digest_config(self, kwargs)
        lexer = pygments.lexers.get_lexer_by_name(self.language)
        tokens_generator = pygments.lex(code, lexer)
        styles_dict = dict(pygments.styles.get_style_by_name(self.code_style))
        default_color_hex = styles_dict[pygments.token.Text]["color"]
        if not default_color_hex:
            default_color_hex = self.color[1:]
        code = ""
        start_index = 0
        t2c = {}
        t2s = {}
        t2w = {}
        for pair in tokens_generator:
            ttype, token = pair
            code += token
            end_index = start_index + len(token)
            span_tuple = (start_index, end_index)
            style_dict = styles_dict[ttype]
            t2c[span_tuple] = "#" + (style_dict["color"] or default_color_hex)
            t2s[span_tuple] = ITALIC if style_dict["italic"] else NORMAL
            t2w[span_tuple] = BOLD if style_dict["bold"] else NORMAL
            start_index = end_index
        t2c.update(self.t2c)
        t2s.update(self.t2s)
        t2w.update(self.t2w)
        kwargs["t2c"] = t2c
        kwargs["t2s"] = t2s
        kwargs["t2w"] = t2w
        super().__init__(code, **kwargs)
        if self.char_width is not None:
            self.set_monospace(self.char_width)

    def set_monospace(self, char_width):
        current_char_index = 0
        for i, char in enumerate(self.text):
            if char == "\n":
                current_char_index = 0
                continue
            self[i].set_x(current_char_index * char_width)
            current_char_index += 1
        self.center()


@contextmanager
def register_font(font_file: typing.Union[str, Path]):
    """Temporarily add a font file to Pango's search path.
    This searches for the font_file at various places. The order it searches it described below.
    1. Absolute path.
    2. Downloads dir.

    Parameters
    ----------
    font_file :
        The font file to add.
    Examples
    --------
    Use ``with register_font(...)`` to add a font file to search
    path.
    .. code-block:: python
        with register_font("path/to/font_file.ttf"):
           a = Text("Hello", font="Custom Font Name")
    Raises
    ------
    FileNotFoundError:
        If the font doesn't exists.
    AttributeError:
        If this method is used on macOS.
    Notes
    -----
    This method of adding font files also works with :class:`CairoText`.
    .. important ::
        This method is available for macOS for ``ManimPango>=v0.2.3``. Using this
        method with previous releases will raise an :class:`AttributeError` on macOS.
    """

    input_folder = Path(get_downloads_dir()).parent.resolve()
    possible_paths = [
        Path(font_file),
        input_folder / font_file,
    ]
    for path in possible_paths:
        path = path.resolve()
        if path.exists():
            file_path = path
            break
    else:
        error = f"Can't find {font_file}." f"Tried these : {possible_paths}"
        raise FileNotFoundError(error)

    try:
        assert manimpango.register_font(str(file_path))
        yield
    finally:
        manimpango.unregister_font(str(file_path))
