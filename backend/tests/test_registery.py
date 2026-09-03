from app.registry.registry import (
    get_all_tools,
    get_enabled_tools,
    get_tool,
)
from app.registry.registry import ToolType


def test_registry_contains_tools():
    tools = get_all_tools()

    assert len(tools) > 0


def test_tool_ids_are_unique():
    tools = get_all_tools()

    tool_ids = [
        tool.tool_id
        for tool in tools
    ]

    assert len(tool_ids) == len(set(tool_ids))


def test_get_existing_tool():
    tool = get_tool("ndvi")

    assert tool is not None
    assert tool.tool_id == "ndvi"
    assert tool.tool_type == ToolType.INDEX


def test_get_nonexistent_tool():
    tool = get_tool("does_not_exist")

    assert tool is None


def test_enabled_tools():
    tools = get_enabled_tools()

    assert len(tools) > 0
    assert all(tool.enabled for tool in tools)


def test_ndvi_definition():
    tool = get_tool("ndvi")

    assert tool is not None
    assert tool.supported_modalities == ["optical"]
    assert set(tool.required_bands) == {"red", "nir"}
    assert tool.min_images == 1
    assert tool.max_images == 1


def test_change_detection_definition():
    tool = get_tool("change_detection")

    assert tool is not None
    assert tool.min_images == 2
    assert tool.max_images == 2
    assert tool.requires_temporal_pair is True


def test_sar_definition():
    tool = get_tool("sar_analysis")

    assert tool is not None
    assert tool.supported_modalities == ["sar"]