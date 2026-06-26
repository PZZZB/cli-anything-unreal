"""UMG Widget Blueprint authoring commands."""

from __future__ import annotations

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor


@click.group("umg")
def umg_group():
    """UMG Widget Blueprint authoring (requires running editor)."""


@umg_group.command("create")
@click.argument("widget_path")
@click.option("--root-class", default="CanvasPanel", help="Root widget class")
@click.option("--root-name", default="RootCanvas", help="Root widget name")
@click.option("--force", is_flag=True, default=False, help="Replace an existing asset")
@click.option("--variable/--no-variable", default=False, help="Expose root widget as a Blueprint variable")
@handle_error
@click.pass_obj
def umg_create(state: AppState, widget_path, root_class, root_name, force, variable):
    """Create a Widget Blueprint with a root widget.

    Example: umg create /Game/UI/WBP_Hud --force
    """
    from cli_anything.unreal.core.umg import create_widget_blueprint

    api = require_editor(state)
    result = create_widget_blueprint(
        api,
        widget_path,
        root_class=root_class,
        root_name=root_name,
        force=force,
        variable=variable,
        project_dir=state.session.project_dir,
    )
    output(result, state)


@umg_group.command("add-widget")
@click.argument("widget_path")
@click.option("--type", "widget_type", required=True, help="Widget class, e.g. TextBlock")
@click.option("--name", "widget_name", required=True, help="New widget name")
@click.option("--parent", default=None, help="CanvasPanel parent name; defaults to root")
@click.option("--text", default=None, help="Text for TextBlock widgets")
@click.option("--x", default=0.0, type=float, help="Canvas slot X")
@click.option("--y", default=0.0, type=float, help="Canvas slot Y")
@click.option("--w", "width", default=-1.0, type=float, help="Canvas slot width")
@click.option("--h", "height", default=-1.0, type=float, help="Canvas slot height")
@click.option("--z", "z_order", default=0, type=int, help="Canvas slot Z order")
@click.option("--variable/--no-variable", default=False, help="Expose widget as a Blueprint variable")
@handle_error
@click.pass_obj
def umg_add_widget(
    state: AppState,
    widget_path,
    widget_type,
    widget_name,
    parent,
    text,
    x,
    y,
    width,
    height,
    z_order,
    variable,
):
    """Add a widget to a CanvasPanel in a Widget Blueprint.

    WIDGET_PATH accepts package, object, generated-class, or WidgetTree subobject paths.
    """
    from cli_anything.unreal.core.umg import add_widget_to_canvas

    api = require_editor(state)
    result = add_widget_to_canvas(
        api,
        widget_path,
        widget_type=widget_type,
        widget_name=widget_name,
        parent=parent,
        text=text,
        x=x,
        y=y,
        width=width,
        height=height,
        z_order=z_order,
        variable=variable,
        project_dir=state.session.project_dir,
    )
    output(result, state)


@umg_group.command("set-image")
@click.argument("widget_path")
@click.option("--name", "widget_name", required=True, help="Existing Image widget name")
@click.option("--texture", "texture_path", default=None, help="Brush resource texture/object path")
@click.option("--x", default=None, type=float, help="Canvas slot X")
@click.option("--y", default=None, type=float, help="Canvas slot Y")
@click.option("--w", "width", default=None, type=float, help="Canvas slot width")
@click.option("--h", "height", default=None, type=float, help="Canvas slot height")
@click.option("--z", "z_order", default=None, type=int, help="Canvas slot Z order")
@handle_error
@click.pass_obj
def umg_set_image(state: AppState, widget_path, widget_name, texture_path, x, y, width, height, z_order):
    """Edit an existing Image widget brush resource and CanvasPanelSlot layout.

    WIDGET_PATH accepts package, object, generated-class, or WidgetTree subobject paths.
    """
    from cli_anything.unreal.core.umg import set_widget_image

    api = require_editor(state)
    result = set_widget_image(
        api,
        widget_path,
        widget_name=widget_name,
        texture_path=texture_path,
        x=x,
        y=y,
        width=width,
        height=height,
        z_order=z_order,
        project_dir=state.session.project_dir,
    )
    output(result, state)


@umg_group.command("tree")
@click.argument("widget_path")
@handle_error
@click.pass_obj
def umg_tree(state: AppState, widget_path):
    """Show the design-time WidgetTree for a Widget Blueprint.

    WIDGET_PATH accepts package, object, generated-class, or WidgetTree subobject paths.
    """
    from cli_anything.unreal.core.umg import get_widget_tree

    api = require_editor(state)
    result = get_widget_tree(api, widget_path, project_dir=state.session.project_dir)
    output(result, state)


@umg_group.command("live-tree")
@click.argument("target")
@click.option("--limit", default=20, type=int, help="Max matching live UserWidget instances")
@handle_error
@click.pass_obj
def umg_live_tree(state: AppState, target, limit):
    """Show runtime child widgets for live UUserWidget instances.

    TARGET matches live instance name/path or generated class name.
    """
    from cli_anything.unreal.core.umg import get_live_widget_tree

    api = require_editor(state)
    result = get_live_widget_tree(
        api,
        target,
        limit=limit,
        project_dir=state.session.project_dir,
    )
    output(result, state)
