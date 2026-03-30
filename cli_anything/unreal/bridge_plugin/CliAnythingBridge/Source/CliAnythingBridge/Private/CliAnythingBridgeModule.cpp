#include "Modules/ModuleManager.h"

class FCliAnythingBridgeModule : public IModuleInterface
{
public:
	virtual void StartupModule() override {}
	virtual void ShutdownModule() override {}
};

IMPLEMENT_MODULE(FCliAnythingBridgeModule, CliAnythingBridge)
