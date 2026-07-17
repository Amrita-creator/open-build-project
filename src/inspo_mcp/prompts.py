"""Detailed, user-invoked workflows for creating original UI kits."""

from __future__ import annotations

import json
from typing import Annotated, Callable

from fastmcp import FastMCP
from pydantic import Field

from inspo_mcp.schemas import Framework


ScreenshotPaths = Annotated[
    list[str],
    Field(
        min_length=2,
        max_length=3,
        description=(
            "Two or three distinct absolute screenshot paths available to the MCP server. "
            "Use forward slashes on Windows."
        ),
    ),
]


def clarify_idea_and_create_ui_kit(
    rough_idea: Annotated[
        str,
        Field(
            min_length=8,
            description="The user's rough product or page idea; it does not need to be complete.",
        ),
    ],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Guide an unclear idea into a strong, evidence-based UI-kit workflow."""

    sources = _sources_json(screenshot_paths)
    return f"""You are preparing an original reusable UI kit with InspoMCP.

The user's rough idea is:
{rough_idea}

The implementation framework is: {framework}
The visual evidence is:
{sources}

Before calling any tool, turn the rough idea into a usable product goal. Ask at
most three short questions, only when the answers are missing:
1. Who is the primary user?
2. What outcome should that user achieve?
3. What is the most important first action (for example, Start free or Book a demo)?

After the user answers, write one normalized product goal using this form:
"Build a [page or app type] for [primary user] that helps them [outcome].
Primary action: [action]."

Then call `create_inspiration_kit` with the normalized goal, framework
`{framework}`, an empty `inspiration_urls` array unless the user supplies a
public supporting URL, and these exact screenshots:
{sources}

Never include passwords, API keys, private keys, customer records, or other
confidential information in a product goal, URL, or screenshot.

Keep the returned `run_id`. Poll `get_status` or `get_vision_analyses` while
M5 runs. Do not invent visual findings for pending, failed, or unavailable
sources. Generate the final kit only after every requested visual analysis is
completed. If status says M5 needs retry, call `retry_vision_analysis`; then
call `generate_reusable_kit` and `get_kit`.

Present an original kit with design direction, page hierarchy, components,
tokens, accessibility needs, responsive behavior, and implementation tasks.
Infer reusable patterns only: never reproduce reference logos, copy, imagery,
branding, or exact geometry.
"""


def create_landing_page_ui_kit(
    product: Annotated[str, Field(min_length=2, description="Product or service name.")],
    audience: Annotated[str, Field(min_length=2, description="Primary target audience.")],
    value: Annotated[str, Field(min_length=5, description="Main outcome or value proposition.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary call to action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a conversion-focused landing-page UI-kit workflow."""

    goal = (
        f"Build a responsive landing page for {audience} using {product} to {value}. "
        f"Make '{primary_action}' the primary call to action."
    )
    return _kit_workflow(
        kit_type="conversion-focused landing page",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Make the value proposition and primary action clear in the first viewport. "
            "Use proof, benefits, and a closing action without copying source copy."
        ),
    )


def create_saas_dashboard_ui_kit(
    product: Annotated[str, Field(min_length=2, description="SaaS product name or type.")],
    user_role: Annotated[str, Field(min_length=2, description="Main dashboard user role.")],
    key_workflow: Annotated[str, Field(min_length=5, description="Main task users complete.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create an operational SaaS-dashboard UI-kit workflow."""

    goal = (
        f"Design a responsive SaaS dashboard for {user_role} using {product} to {key_workflow}. "
        "Prioritize clear navigation, data hierarchy, and the most frequent workflow."
    )
    return _kit_workflow(
        kit_type="SaaS dashboard",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize orientation, data scanning, empty and loading states, accessible tables or cards, "
            "and responsive behavior for narrow screens."
        ),
    )


def create_ai_product_ui_kit(
    product: Annotated[str, Field(min_length=2, description="AI product name or concept.")],
    audience: Annotated[str, Field(min_length=2, description="Primary intended users.")],
    main_task: Annotated[str, Field(min_length=5, description="Core job the AI helps users complete.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary call to action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a trustworthy AI-product UI-kit workflow."""

    goal = (
        f"Build a product experience for {audience} using {product} to {main_task}. "
        f"Make '{primary_action}' the primary action and communicate AI capabilities honestly."
    )
    return _kit_workflow(
        kit_type="AI product experience",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Make the AI value concrete, explain user control where relevant, use trustworthy proof, "
            "and avoid implying capabilities the product does not have."
        ),
    )


def create_ecommerce_ui_kit(
    brand: Annotated[str, Field(min_length=2, description="Brand or store name.")],
    shoppers: Annotated[str, Field(min_length=2, description="Target shoppers.")],
    product_category: Annotated[str, Field(min_length=2, description="Main product category.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary shopping action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a discovery- and conversion-focused ecommerce UI-kit workflow."""

    goal = (
        f"Build an ecommerce experience for {shoppers} shopping {product_category} from {brand}. "
        f"Make '{primary_action}' the primary shopping action."
    )
    return _kit_workflow(
        kit_type="ecommerce storefront",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize product discovery, scannable product cards, trust signals, transparent pricing or delivery "
            "details, and a low-friction mobile path to the primary action."
        ),
    )


def create_portfolio_ui_kit(
    professional: Annotated[str, Field(min_length=2, description="Person, studio, or creative practice.")],
    audience: Annotated[str, Field(min_length=2, description="People the portfolio should persuade.")],
    proof: Annotated[str, Field(min_length=5, description="Work, expertise, or proof to emphasize.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary contact action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a portfolio and client-enquiry UI-kit workflow."""

    goal = (
        f"Build a portfolio for {professional} that persuades {audience} through {proof}. "
        f"Make '{primary_action}' the primary contact action."
    )
    return _kit_workflow(
        kit_type="professional portfolio",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize a clear personal or studio point of view, strong case-study hierarchy, credible proof, "
            "and an easy path to begin a conversation."
        ),
    )


def create_education_platform_ui_kit(
    product: Annotated[str, Field(min_length=2, description="Education product or institution.")],
    learners: Annotated[str, Field(min_length=2, description="Target learners.")],
    learning_outcome: Annotated[str, Field(min_length=5, description="Outcome learners should achieve.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary enrolment or learning action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create an education-platform UI-kit workflow."""

    goal = (
        f"Build an education platform for {learners} using {product} to {learning_outcome}. "
        f"Make '{primary_action}' the primary learning action."
    )
    return _kit_workflow(
        kit_type="education platform",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize learning-path clarity, progress and outcomes, credible instructor or curriculum proof, "
            "inclusive reading hierarchy, and an obvious next learning step."
        ),
    )


def create_mobile_app_marketing_ui_kit(
    app: Annotated[str, Field(min_length=2, description="Mobile app name or concept.")],
    audience: Annotated[str, Field(min_length=2, description="Target app users.")],
    benefit: Annotated[str, Field(min_length=5, description="Most important app benefit.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary download or signup action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a mobile-app marketing UI-kit workflow."""

    goal = (
        f"Build a mobile app marketing page for {audience} using {app} to {benefit}. "
        f"Make '{primary_action}' the primary action."
    )
    return _kit_workflow(
        kit_type="mobile app marketing page",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize the app benefit, device or product-media focal point, concise feature proof, app-store or "
            "signup conversion, and a strong narrow-screen experience."
        ),
    )


def create_booking_service_ui_kit(
    service: Annotated[str, Field(min_length=2, description="Bookable service or business.")],
    customers: Annotated[str, Field(min_length=2, description="Target customers.")],
    booking_outcome: Annotated[str, Field(min_length=5, description="What the customer should be able to book.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary booking action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a service-booking UI-kit workflow."""

    goal = (
        f"Build a service-booking experience for {customers} using {service} to {booking_outcome}. "
        f"Make '{primary_action}' the primary booking action."
    )
    return _kit_workflow(
        kit_type="booking service",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize service clarity, availability and scheduling confidence, pricing or expectation transparency, "
            "trust signals, and a low-friction booking path."
        ),
    )


def create_developer_tool_ui_kit(
    product: Annotated[str, Field(min_length=2, description="Developer product, SDK, or API name.")],
    developers: Annotated[str, Field(min_length=2, description="Target developer audience.")],
    key_workflow: Annotated[str, Field(min_length=5, description="Main developer task the product enables.")],
    primary_action: Annotated[str, Field(min_length=2, description="Primary developer conversion action.")],
    screenshot_paths: ScreenshotPaths,
    framework: Framework = "nextjs-tailwind",
) -> str:
    """Create a developer-tool UI-kit workflow."""

    goal = (
        f"Build a developer-product experience for {developers} using {product} to {key_workflow}. "
        f"Make '{primary_action}' the primary developer action."
    )
    return _kit_workflow(
        kit_type="developer tool",
        project_goal=goal,
        screenshot_paths=screenshot_paths,
        framework=framework,
        design_focus=(
            "Prioritize technical clarity, workflow proof, documentation or integration discoverability, readable code or "
            "API examples where appropriate, and an obvious path to start building."
        ),
    )


def _kit_workflow(
    *,
    kit_type: str,
    project_goal: str,
    screenshot_paths: list[str],
    framework: Framework,
    design_focus: str,
) -> str:
    """Render the common safe, evidence-first workflow for a specific UI-kit type."""

    request = {
        "project_goal": project_goal,
        "framework": framework,
        "inspiration_urls": [],
        "inspiration_screenshots": screenshot_paths,
    }
    return f"""Create an original {kit_type} UI kit with InspoMCP.

Normalized product goal:
{project_goal}

Design focus:
{design_focus}

Call `create_inspiration_kit` with this exact request:
```json
{json.dumps(request, ensure_ascii=False, indent=2)}
```

Keep the returned `run_id` and follow this workflow:
1. Use `get_status` or `get_vision_analyses` to monitor M5 visual analysis.
2. Explain source warnings clearly. Do not make up design findings for pending,
   failed, blocked, or unavailable sources.
3. Only when every requested visual analysis is complete, call `generate_reusable_kit`.
   If M5 needs retry, call `retry_vision_analysis` first.
4. Call `get_kit` and present the design direction, blueprint, component cards,
   tokens, and prioritized build tasks.
5. Offer `generate_component_code` only after the kit is ready and the user
   chooses a component card.

Quality rules:
- Treat the screenshots as pattern evidence, never as material to copy.
- Do not reproduce source logos, text, images, branding, or exact geometry.
- Keep one primary action clear, make the page responsive, preserve keyboard
  focus, and use text contrast that supports readability.
- State any assumptions and distinguish them from observed evidence.
- Never include passwords, API keys, private keys, customer records, or other
  confidential information in a product goal, URL, or screenshot.
"""


def _sources_json(screenshot_paths: list[str]) -> str:
    """Render screenshot paths safely and readably inside a generated prompt."""

    return json.dumps(screenshot_paths, ensure_ascii=False, indent=2)


PromptFunction = Callable[..., str]

PROMPT_LIBRARY: tuple[tuple[PromptFunction, dict[str, object]], ...] = (
    (
        clarify_idea_and_create_ui_kit,
        {
            "title": "Clarify an idea and create a UI kit",
            "description": "Turn a rough product idea into a clear product goal and evidence-first UI-kit workflow.",
            "tags": {"discovery", "workflow"},
        },
    ),
    (
        create_landing_page_ui_kit,
        {
            "title": "Create a landing-page UI kit",
            "description": "Create an original, conversion-focused landing-page kit from reference screenshots.",
            "tags": {"landing-page", "marketing"},
        },
    ),
    (
        create_saas_dashboard_ui_kit,
        {
            "title": "Create a SaaS-dashboard UI kit",
            "description": "Create a workflow-focused SaaS dashboard kit from reference screenshots.",
            "tags": {"saas", "dashboard"},
        },
    ),
    (
        create_ai_product_ui_kit,
        {
            "title": "Create an AI-product UI kit",
            "description": "Create a clear and trustworthy AI product experience from reference screenshots.",
            "tags": {"ai", "product"},
        },
    ),
    (
        create_ecommerce_ui_kit,
        {
            "title": "Create an ecommerce UI kit",
            "description": "Create a product-discovery and conversion-focused storefront kit.",
            "tags": {"ecommerce", "storefront"},
        },
    ),
    (
        create_portfolio_ui_kit,
        {
            "title": "Create a portfolio UI kit",
            "description": "Create a portfolio and enquiry experience that emphasizes credible proof.",
            "tags": {"portfolio", "creative"},
        },
    ),
    (
        create_education_platform_ui_kit,
        {
            "title": "Create an education-platform UI kit",
            "description": "Create a learning-path and enrolment-focused education experience.",
            "tags": {"education", "learning"},
        },
    ),
    (
        create_mobile_app_marketing_ui_kit,
        {
            "title": "Create a mobile-app marketing UI kit",
            "description": "Create a product-marketing kit focused on app adoption and mobile conversion.",
            "tags": {"mobile", "marketing"},
        },
    ),
    (
        create_booking_service_ui_kit,
        {
            "title": "Create a booking-service UI kit",
            "description": "Create a service-booking experience focused on trust and conversion.",
            "tags": {"booking", "service"},
        },
    ),
    (
        create_developer_tool_ui_kit,
        {
            "title": "Create a developer-tool UI kit",
            "description": "Create a developer-product experience with clear technical workflow guidance.",
            "tags": {"developer-tools", "b2b"},
        },
    ),
)


def register_user_workflow_prompts(mcp: FastMCP) -> None:
    """Register all user-invoked UI-kit workflow prompts with one MCP server."""

    for prompt, metadata in PROMPT_LIBRARY:
        mcp.prompt(prompt, **metadata)
