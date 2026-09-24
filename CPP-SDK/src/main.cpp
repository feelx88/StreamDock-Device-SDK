#include <iostream>
#include <vector>
#include <DeviceManager/devicemanager.h>
#include "test.h"

void doSomething(std::shared_ptr<StreamDock> device)
{
	TEST_293V2::test(device);
	TEST_293V3::test(device);
	TEST_293sV2::test(device);
	TEST_293sV3::test(device);
	TEST_M18::test(device);
	TEST_N3V2::test(device);
	TEST_N3V25::test(device);
	TEST_N1::test(device);
	TEST_N4::test(device);
	TEST_N4Pro::test(device);
	TEST_XL::test(device);
	TEST_M3::test(device);
	TEST_M18V3::test(device);
	TEST_Mini::test(device);
	TEST_K1Pro::test(device);
	TEST_H1Pro::test(device);
}

int main()
{
	DeviceManager::instance().enumerator();
	std::vector<std::shared_ptr<StreamDock>> initialDevices;
	for (const auto& entry : DeviceManager::instance().getStreamDocks())
		initialDevices.push_back(entry.second);
	DeviceManager::instance().listen([](std::shared_ptr<StreamDock> device)
		{
			try { doSomething(device); }
			catch (const std::exception& e)
			{
				std::cerr << "Hotplug setup failed: " << e.what() << std::endl;
			}
		});
	for (const auto &device : initialDevices)
	{
		try
		{
			doSomething(device);
		}
		catch (const std::exception &e)
		{
			std::cerr << "Exception: " << e.what() << std::endl;
		}
		catch (...)
		{
			std::cerr << "Unknown exception occurred" << std::endl;
		}
	}
	if(initialDevices.empty())
	{
		std::cout << "No StreamDock devices found. Connect a device to run tests and check your PID && VID." << std::endl;
	}

	std::cerr << "Press enter to exit..." << std::endl;
	std::cin.get();
	return 0;
}
