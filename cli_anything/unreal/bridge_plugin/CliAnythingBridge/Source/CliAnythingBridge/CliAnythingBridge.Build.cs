using UnrealBuildTool;

public class CliAnythingBridge : ModuleRules
{
	public CliAnythingBridge(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"UMG",
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"RHI",
			"RenderCore",
			"Slate",
			"SlateCore",
			"UMGEditor",
			"UnrealEd",
		});
	}
}
