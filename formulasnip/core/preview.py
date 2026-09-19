from __future__ import annotations

import html
import re
from pathlib import Path

from formulasnip.core.latex import normalize_latex

MATHJAX_SCRIPT_NAME = "tex-svg-full.js"
_ENVIRONMENT_TOKEN_RE = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")


def is_formula_previewable(latex: str) -> bool:
    """Return whether ``latex`` is structurally safe to send to MathJax.

    This preflight deliberately does not attempt to render or validate TeX. It
    runs in recognition workers where Qt WebEngine is unavailable, while the
    browser-owned MathJax instance remains the authority on rendering support.
    """

    normalized = normalize_latex(latex)
    if not normalized or "\x00" in normalized:
        return False
    if not _has_balanced_braces(normalized):
        return False
    return _has_balanced_environments(normalized)


def mathjax_script_path() -> Path:
    """Return the vendored, offline MathJax component used by the GUI preview."""

    return (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "MathJax-3.2.2"
        / "es5"
        / MATHJAX_SCRIPT_NAME
    )


def build_mathjax_html(latex: str, request_id: int) -> str:
    """Build one offline MathJax document without interpolating TeX into JS."""

    normalized = normalize_latex(latex)
    if not normalized:
        raise ValueError("公式预览内容为空")
    # This lands in an ordinary text node. The HTML parser decodes the entities
    # back to the exact TeX characters without ever treating user input as tags
    # or JavaScript source.
    safe_formula = html.escape(normalized, quote=True)
    safe_request_id = int(request_id)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; script-src 'self' file: 'unsafe-inline' 'unsafe-eval';
                 style-src 'unsafe-inline'; img-src data:; font-src 'self' file: data:;
                 connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none';">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; }}
    body {{
      box-sizing: border-box; padding: 12px; background: #fff;
      color: #172033; font-size: 12px;
    }}
    #viewport {{
      width: 100%; height: 100%; box-sizing: border-box; overflow: auto;
      display: flex; align-items: center; scrollbar-color: #aab4c3 #f4f6f9;
    }}
    #formula {{
      display: inline-block; flex: 0 0 auto; margin: auto; min-width: max-content;
      font-size: 20px;
    }}
    mjx-container[display="true"] {{ margin: 0 !important; min-width: max-content; }}
    mjx-container a {{ pointer-events: none !important; }}
    mjx-merror {{ color: #b42318 !important; }}
    ::-webkit-scrollbar {{ width: 9px; height: 9px; }}
    ::-webkit-scrollbar-track {{ background: #f4f6f9; }}
    ::-webkit-scrollbar-thumb {{ background: #aab4c3; border-radius: 5px; }}
  </style>
  <script>
    window.__formulaPreview = {{requestId: {safe_request_id}, state: 'loading', error: ''}};
    window.MathJax = {{
      tex: {{
        inlineMath: [['\\\\(', '\\\\)']],
        displayMath: [['\\\\[', '\\\\]']],
        processEscapes: true,
        packages: {{
          '[+]': ['ams', 'newcommand'],
          '[-]': ['noundefined']
        }}
      }},
      svg: {{fontCache: 'global', scale: 1.15}},
      options: {{enableMenu: false}},
      startup: {{
        ready: function () {{
          MathJax.startup.defaultReady();
          MathJax.startup.promise.then(function () {{
            var error = document.querySelector(
              'mjx-merror, g[data-mml-node="merror"]'
            );
            if (error) {{
              window.__formulaPreview.state = 'error';
              window.__formulaPreview.error = error.textContent || 'MathJax parse error';
            }} else {{
              window.__formulaPreview.state = 'ready';
            }}
          }}).catch(function (error) {{
            window.__formulaPreview.state = 'error';
            window.__formulaPreview.error = String(error);
          }});
        }}
      }}
    }};
  </script>
</head>
<body>
  <div id="viewport"><div id="formula">\\[{safe_formula}\\]</div></div>
  <script src="{MATHJAX_SCRIPT_NAME}"
          onerror="window.__formulaPreview.state='error';
                   window.__formulaPreview.error='MathJax resource unavailable';"></script>
</body>
</html>"""


def _has_balanced_environments(latex: str) -> bool:
    stack: list[str] = []
    for operation, environment in _ENVIRONMENT_TOKEN_RE.findall(latex):
        environment = environment.strip()
        if not environment:
            return False
        if operation == "begin":
            stack.append(environment)
        elif not stack or stack.pop() != environment:
            return False
    return not stack


def _has_balanced_braces(latex: str) -> bool:
    depth = 0
    for index, character in enumerate(latex):
        if character not in "{}" or _is_escaped(latex, index):
            continue
        depth += 1 if character == "{" else -1
        if depth < 0:
            return False
    return depth == 0


def _is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and value[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1
