from __future__ import annotations

import html
import json
import re
from pathlib import Path

from formulasnip.core.latex import normalize_latex
from formulasnip.core.limits import LATEX_LIMIT_MESSAGE, MAX_LATEX_CHARS

MATHJAX_SCRIPT_NAME = "tex-svg-full.js"
_ENVIRONMENT_TOKEN_RE = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")


def is_formula_previewable(latex: str) -> bool:
    """Return whether ``latex`` is structurally safe to send to MathJax.

    This preflight deliberately does not attempt to render or validate TeX. It
    runs in recognition workers where Qt WebEngine is unavailable, while the
    browser-owned MathJax instance remains the authority on rendering support.
    """

    if len(latex) > MAX_LATEX_CHARS:
        return False
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
    """Build the reusable offline MathJax document.

    The initial formula is inserted as escaped text. Later previews update this
    same document through :func:`build_mathjax_update_script`, so the 2.3 MiB
    MathJax runtime only needs to be loaded once per application session.
    """

    if len(latex) > MAX_LATEX_CHARS:
        raise ValueError(LATEX_LIMIT_MESSAGE)
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
    window.__formulaGeneration = 0;
    window.__queuedFormula = null;
    window.__mathJaxReady = false;
    window.__renderQueue = Promise.resolve();

    window.__finishFormulaPreview = function (requestId, generation) {{
      if (generation !== window.__formulaGeneration ||
          requestId !== window.__formulaPreview.requestId) {{
        return;
      }}
      var error = document.querySelector(
        'mjx-merror, g[data-mml-node="merror"]'
      );
      if (error) {{
        window.__formulaPreview.state = 'error';
        window.__formulaPreview.error = error.textContent || 'MathJax parse error';
      }} else {{
        window.__formulaPreview.state = 'ready';
        window.__formulaPreview.error = '';
      }}
    }};

    window.__renderFormulaPreview = function (latex, requestId, generation) {{
      window.__renderQueue = window.__renderQueue.catch(function () {{}}).then(
        function () {{
          if (generation !== window.__formulaGeneration) {{
            return;
          }}
          var target = document.getElementById('formula');
          MathJax.typesetClear([target]);
          MathJax.texReset();
          var inputJax = MathJax.startup.document.inputJax;
          var tex = inputJax.find(function (jax) {{
            return jax.name === 'TeX' && jax.parseOptions;
          }});
          if (!tex) {{
            throw new Error('MathJax TeX input unavailable');
          }}
          tex.parseOptions.clear();
          ['new-Command', 'new-Delimiter', 'new-Environment'].forEach(
            function (mapName) {{
              var userMap = tex.parseOptions.handlers.retrieve(mapName);
              if (userMap && userMap.map) {{
                userMap.map.clear();
              }}
            }}
          );
          target.textContent = '\\\\[' + latex + '\\\\]';
          return MathJax.typesetPromise([target]).then(function () {{
            window.__finishFormulaPreview(requestId, generation);
          }}).catch(function (error) {{
            if (generation === window.__formulaGeneration &&
                requestId === window.__formulaPreview.requestId) {{
              window.__formulaPreview.state = 'error';
              window.__formulaPreview.error = String(error);
            }}
          }});
        }}
      );
    }};

    window.__setFormulaPreview = function (latex, requestId) {{
      var generation = ++window.__formulaGeneration;
      window.__formulaPreview = {{requestId: requestId, state: 'loading', error: ''}};
      window.__queuedFormula = {{
        latex: latex, requestId: requestId, generation: generation
      }};
      if (window.__mathJaxReady) {{
        var queued = window.__queuedFormula;
        window.__queuedFormula = null;
        window.__renderFormulaPreview(
          queued.latex, queued.requestId, queued.generation
        );
      }}
      return true;
    }};

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
            window.__mathJaxReady = true;
            if (window.__queuedFormula) {{
              var queued = window.__queuedFormula;
              window.__queuedFormula = null;
              window.__renderFormulaPreview(
                queued.latex, queued.requestId, queued.generation
              );
            }} else {{
              window.__finishFormulaPreview({safe_request_id}, 0);
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


def build_mathjax_update_script(latex: str, request_id: int) -> str:
    """Build a safe JavaScript call that updates the persistent preview page."""

    if len(latex) > MAX_LATEX_CHARS:
        raise ValueError(LATEX_LIMIT_MESSAGE)
    normalized = normalize_latex(latex)
    if not normalized:
        raise ValueError("公式预览内容为空")
    encoded_formula = json.dumps(normalized, ensure_ascii=True)
    safe_request_id = int(request_id)
    return f"""(function () {{
      if (typeof window.__setFormulaPreview !== 'function') {{
        return false;
      }}
      return window.__setFormulaPreview({encoded_formula}, {safe_request_id});
    }})()"""


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
