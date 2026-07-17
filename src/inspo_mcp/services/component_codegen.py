"""M8 deterministic starter-code generation for one M6 component card."""

from __future__ import annotations

import re

from inspo_mcp.schemas import (
    ComponentCard,
    ComponentCodeGeneration,
    Framework,
    GeneratedCodeFile,
    InspirationKit,
)


class ComponentNotFoundError(ValueError):
    """Raised when a requested component is absent from the persisted M6 kit."""


class ComponentCodeGenerator:
    """Generate original, framework-aware component scaffolds from M6 contracts."""

    def generate(
        self,
        kit: InspirationKit,
        *,
        framework: Framework,
        component_name: str,
    ) -> ComponentCodeGeneration:
        """Return code for exactly one named component in a durable kit."""

        card = _find_component(kit.component_cards, component_name)
        if framework == "nextjs-tailwind":
            files = [_tailwind_file(card, kit)]
            dependencies = ["react", "tailwindcss"]
        elif framework == "react-css":
            files = [_react_file(card), _css_file(card, kit)]
            dependencies = ["react"]
        else:
            files = [_html_file(card), _css_file(card, kit, extension="css")]
            dependencies = []
        return ComponentCodeGeneration(
            run_id=kit.run_id,
            component_name=card.name,
            framework=framework,
            files=files,
            dependencies=dependencies,
            implementation_notes=[
                f"Purpose: {card.purpose}",
                f"Responsive behavior: {card.responsive_behavior}",
                *card.accessibility_notes,
                "Replace placeholder copy and media with original product content.",
            ],
            warnings=kit.warnings,
        )


def _find_component(cards: list[ComponentCard], component_name: str) -> ComponentCard:
    normalized = component_name.strip().casefold()
    for card in cards:
        if card.name.casefold() == normalized:
            return card
    available = ", ".join(card.name for card in cards)
    raise ComponentNotFoundError(
        f"Component '{component_name}' is not in this kit. Available components: {available}."
    )


def _tailwind_file(card: ComponentCard, kit: InspirationKit) -> GeneratedCodeFile:
    return GeneratedCodeFile(
        path=f"components/{card.name}.tsx",
        language="tsx",
        content=_tsx_source(card, style="tailwind", kit=kit),
    )


def _react_file(card: ComponentCard) -> GeneratedCodeFile:
    slug = _kebab_case(card.name)
    return GeneratedCodeFile(
        path=f"components/{card.name}.tsx",
        language="tsx",
        content=f'import "./{slug}.css";\n\n' + _tsx_source(card, style="css", kit=None),
    )


def _css_file(
    card: ComponentCard,
    kit: InspirationKit,
    *,
    extension: str = "css",
) -> GeneratedCodeFile:
    slug = _kebab_case(card.name)
    tokens = kit.design_tokens
    return GeneratedCodeFile(
        path=f"components/{slug}.{extension}",
        language="css",
        content=f"""/* Original tokens synthesized for this kit. */
.{slug} {{
  --surface: {tokens.colors['surface']};
  --text: {tokens.colors['text']};
  --muted-text: {tokens.colors['muted_text']};
  --accent: {tokens.colors['accent']};
  --section-space: {tokens.spacing['section']};
  --card-radius: {tokens.radius['card']};
  --card-shadow: {tokens.shadow['card']};
  color: var(--text);
}}

.{slug}__nav {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
  padding-block: 1rem;
}}

.{slug}__list, .{slug}__actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  list-style: none;
  margin: 0;
  padding: 0;
}}

.{slug}__grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: {tokens.spacing['card']};
  padding: 0;
  list-style: none;
}}

.{slug}__grid--columns-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.{slug}__grid--columns-4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}

.{slug}__card {{
  padding: {tokens.spacing['card']};
  border-radius: var(--card-radius);
  background: var(--surface);
  box-shadow: var(--card-shadow);
}}

.{slug}__body {{ color: var(--muted-text); line-height: 1.6; }}
.{slug}--centered {{ text-align: center; }}
.{slug}--dark {{ background: {tokens.colors['text']}; color: {tokens.colors['surface']}; }}

.{slug}__action {{
  display: inline-flex;
  min-height: 2.75rem;
  align-items: center;
  justify-content: center;
  border-radius: {tokens.radius['button']};
  background: var(--accent);
  color: {tokens.colors['surface']};
  font-weight: 700;
  text-decoration: none;
}}

.{slug}__action:focus-visible {{
  outline: 3px solid var(--text);
  outline-offset: 3px;
}}

.{slug}__action--secondary {{
  background: transparent;
  box-shadow: inset 0 0 0 1px currentColor;
  color: var(--text);
}}

@media (max-width: 48rem) {{
  .{slug} {{
    padding-inline: 1rem;
  }}
  .{slug}__grid {{ grid-template-columns: 1fr; }}
}}
""",
    )


def _html_file(card: ComponentCard) -> GeneratedCodeFile:
    slug = _kebab_case(card.name)
    return GeneratedCodeFile(
        path=f"components/{slug}.html",
        language="html",
        content=_html_source(card, slug),
    )


def _tsx_source(card: ComponentCard, *, style: str, kit: InspirationKit | None) -> str:
    slug = _kebab_case(card.name)
    classes = _classes(card.name, style, kit)
    if card.name == "HeaderNavigation":
        header_class = _variant_class(
            classes["root"],
            variant_name="variant",
            tailwind_condition='variant === "dark"',
            tailwind_classes="bg-slate-950 text-white",
            style=style,
        )
        return f'''import type {{ ReactNode }} from "react";

type NavigationItem = {{ label: string; href: string }};

export type HeaderNavigationProps = {{
  brandSlot: ReactNode;
  navigationItems: NavigationItem[];
  utilityActions?: ReactNode;
  variant?: "light" | "dark" | "compact";
}};

export function HeaderNavigation({{
  brandSlot,
  navigationItems,
  utilityActions,
  variant = "light",
}}: HeaderNavigationProps) {{
  return (
    <header className={{{header_class}}}>
      <nav aria-label="Primary navigation" className="{classes['nav']}">
        <div>{{brandSlot}}</div>
        <ul className="{classes['list']}">
          {{navigationItems.map((item) => (
            <li key={{item.href}}><a className="{classes['link']}" href={{item.href}}>{{item.label}}</a></li>
          ))}}
        </ul>
        <div className="{classes['utility']}">{{utilityActions}}</div>
      </nav>
    </header>
  );
}}
'''
    if card.name == "PrimaryAction":
        action_class = (
            f"`{classes['action']} ${{size === \"lg\" ? \"px-6 py-4 text-lg\" : \"\"}} "
            f"${{variant === \"secondary\" ? \"bg-transparent ring-1 ring-current\" : \"\"}}`"
            if style == "tailwind"
            else f"`{classes['action']} {classes['action']}--${{size}} {classes['action']}--${{variant}}`"
        )
        return f'''import type {{ ReactNode }} from "react";

export type PrimaryActionProps = {{
  label: string;
  href: string;
  icon?: ReactNode;
  size?: "sm" | "md" | "lg";
  variant?: "primary" | "secondary" | "text";
}};

export function PrimaryAction({{
  label,
  href,
  icon,
  size = "md",
  variant = "primary",
}}: PrimaryActionProps) {{
  return (
    <a className={{{action_class}}} href={{href}}>
      <span>{{label}}</span>{{icon ? <span aria-hidden="true">{{icon}}</span> : null}}
    </a>
  );
}}
'''
    if card.name == "ContentCardGrid":
        grid_class = (
            f"`{classes['grid']} ${{columns === 4 ? \"lg:grid-cols-4\" : \"lg:grid-cols-3\"}}`"
            if style == "tailwind"
            else f"`{classes['grid']} {classes['grid']}--columns-${{columns}}`"
        )
        return f'''import type {{ ReactNode }} from "react";

type ContentCardItem = {{
  title: string;
  description: string;
  href?: string;
  imageOrIcon?: ReactNode;
}};

export type ContentCardGridProps = {{
  items: ContentCardItem[];
  columns?: 2 | 3 | 4;
  cardVariant?: "feature" | "category" | "editorial";
  sectionTitle: string;
}};

export function ContentCardGrid({{ items, columns = 3, sectionTitle }}: ContentCardGridProps) {{
  return (
    <section className="{classes['root']}" aria-labelledby="content-card-grid-title">
      <h2 id="content-card-grid-title" className="{classes['heading']}">{{sectionTitle}}</h2>
      <ul className={{{grid_class}}}>
        {{items.map((item) => (
          <li key={{item.title}} className="{classes['card']}">
            {{item.imageOrIcon ? <div aria-hidden="true">{{item.imageOrIcon}}</div> : null}}
            <h3 className="{classes['card_heading']}">{{item.title}}</h3>
            <p className="{classes['body']}">{{item.description}}</p>
            {{item.href ? <a className="{classes['link']}" href={{item.href}}>Explore <span className="sr-only">{{item.title}}</span></a> : null}}
          </li>
        ))}}
      </ul>
    </section>
  );
}}
'''
    if card.name == "ProofStrip":
        proof_class = _variant_class(
            classes["root"],
            variant_name="emphasis",
            tailwind_condition='emphasis === "bordered"',
            tailwind_classes="border",
            style=style,
        )
        return f'''import type {{ ReactNode }} from "react";

type ProofItem = {{ label: string; supportingText?: string; icon?: ReactNode }};

export type ProofStripProps = {{
  items: ProofItem[];
  emphasis?: "inline" | "bordered" | "surface";
}};

export function ProofStrip({{ items, emphasis = "surface" }}: ProofStripProps) {{
  return (
    <section className={{{proof_class}}} aria-label="Supporting proof">
      <ul className="{classes['list']}">
        {{items.map((item) => (
          <li key={{item.label}} className="{classes['proof_item']}">
            {{item.icon ? <span aria-hidden="true">{{item.icon}}</span> : null}}
            <span><strong>{{item.label}}</strong>{{item.supportingText ? ` — ${{item.supportingText}}` : ""}}</span>
          </li>
        ))}}
      </ul>
    </section>
  );
}}
'''
    hero_class = _variant_class(
        classes["root"],
        variant_name="alignment",
        tailwind_condition='alignment === "centered"',
        tailwind_classes="text-center",
        style=style,
    )
    return f'''import type {{ ReactNode }} from "react";

export type HeroPanelProps = {{
  eyebrow?: string;
  heading: string;
  body: string;
  media?: ReactNode;
  actions?: ReactNode;
  alignment?: "split" | "centered" | "media-forward";
}};

export function HeroPanel({{
  eyebrow,
  heading,
  body,
  media,
  actions,
  alignment = "split",
}}: HeroPanelProps) {{
  return (
    <section className={{{hero_class}}}>
      <div className="{classes['content']}">
        {{eyebrow ? <p className="{classes['eyebrow']}">{{eyebrow}}</p> : null}}
        <h1 className="{classes['heading']}">{{heading}}</h1>
        <p className="{classes['body']}">{{body}}</p>
        {{actions ? <div className="{classes['actions']}">{{actions}}</div> : null}}
      </div>
      {{media ? <div className="{classes['media']}">{{media}}</div> : null}}
    </section>
  );
}}
'''


def _classes(component_name: str, style: str, kit: InspirationKit | None) -> dict[str, str]:
    slug = _kebab_case(component_name)
    if style == "css":
        return {
            "root": slug,
            "nav": f"{slug}__nav",
            "list": f"{slug}__list",
            "link": f"{slug}__link",
            "utility": f"{slug}__utility",
            "action": f"{slug}__action",
            "heading": f"{slug}__heading",
            "grid": f"{slug}__grid",
            "card": f"{slug}__card",
            "card_heading": f"{slug}__card-heading",
            "body": f"{slug}__body",
            "proof_item": f"{slug}__item",
            "content": f"{slug}__content",
            "eyebrow": f"{slug}__eyebrow",
            "actions": f"{slug}__actions",
            "media": f"{slug}__media",
        }
    accent = kit.design_tokens.colors["accent"] if kit else "blue"
    return {
        "root": "mx-auto grid max-w-7xl gap-8 px-6 py-16 md:grid-cols-2 md:items-center",
        "nav": "mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-4",
        "list": "hidden items-center gap-5 md:flex",
        "link": "rounded text-sm font-medium hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4",
        "utility": "flex items-center gap-3",
        "action": f"inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[{accent}] px-5 py-3 font-semibold text-white shadow-sm transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4",
        "heading": "text-3xl font-bold tracking-tight md:text-4xl",
        "grid": "mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3",
        "card": "rounded-2xl border border-slate-200 bg-white p-6 shadow-sm",
        "card_heading": "text-lg font-semibold",
        "body": "mt-3 text-base leading-7 text-slate-600",
        "proof_item": "flex items-start gap-3",
        "content": "max-w-2xl",
        "eyebrow": f"mb-3 text-sm font-semibold uppercase tracking-wider text-[{accent}]",
        "actions": "mt-7 flex flex-wrap gap-3",
        "media": "min-h-64 rounded-2xl bg-slate-100",
    }


def _variant_class(
    base_class: str,
    *,
    variant_name: str,
    tailwind_condition: str,
    tailwind_classes: str,
    style: str,
) -> str:
    """Emit a Tailwind conditional or a CSS modifier without mixing frameworks."""

    if style == "tailwind":
        return f'`{base_class} ${{{tailwind_condition} ? "{tailwind_classes}" : ""}}`'
    return f"`{base_class} {base_class}--${{{variant_name}}}`"


def _html_source(card: ComponentCard, slug: str) -> str:
    if card.name == "PrimaryAction":
        return f'''<a class="{slug} {slug}__action" href="{{{{href}}}}">
  <span>{{{{label}}}}</span>
</a>
'''
    if card.name == "ContentCardGrid":
        return f'''<section class="{slug}" aria-labelledby="{slug}-title">
  <h2 id="{slug}-title">{{{{section_title}}}}</h2>
  <ul class="{slug}__grid">
    <!-- Repeat this item from your data source. -->
    <li class="{slug}__card"><h3>{{{{item_title}}}}</h3><p>{{{{item_description}}}}</p></li>
  </ul>
</section>
'''
    if card.name == "HeaderNavigation":
        return f'''<header class="{slug}">
  <nav class="{slug}__nav" aria-label="Primary navigation">
    <a href="/" aria-label="Home">{{{{brand}}}}</a>
    <ul class="{slug}__list"><li><a href="{{{{href}}}}">{{{{label}}}}</a></li></ul>
  </nav>
</header>
'''
    if card.name == "ProofStrip":
        return f'''<section class="{slug}" aria-label="Supporting proof">
  <ul><li><strong>{{{{proof_label}}}}</strong> {{{{supporting_text}}}}</li></ul>
</section>
'''
    return f'''<section class="{slug}">
  <div class="{slug}__content">
    <p class="{slug}__eyebrow">{{{{eyebrow}}}}</p>
    <h1>{{{{heading}}}}</h1>
    <p>{{{{body}}}}</p>
    <a class="{slug}__action" href="{{{{action_href}}}}">{{{{action_label}}}}</a>
  </div>
  <div class="{slug}__media">{{{{media}}}}</div>
</section>
'''


def _kebab_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", value).lower()
