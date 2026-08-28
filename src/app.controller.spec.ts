import { Test } from "@nestjs/testing";
import { AppController } from "./app.controller";
import { AppService } from "./app.service";

describe("AppController", () => {
  let appController: AppController;

  beforeEach(async () => {
    const moduleRef = await Test.createTestingModule({
      controllers: [AppController],
      providers: [AppService],
    }).compile();

    appController = moduleRef.get<AppController>(AppController);
  });

  describe("root", () => {
    it('should return "Hello everyone!"', () => {
      expect(appController.getHello()).toBe("Hello everyone!");
    });
  });

  describe("health", () => {
    it('should return { status: "ok" }', () => {
      expect(appController.getHealth()).toEqual({ status: "ok" });
    });
  });
});
