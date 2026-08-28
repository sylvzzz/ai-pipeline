import { Test } from "@nestjs/testing";
import { AppController } from "../src/app.controller";
import { AppService } from "../src/app.service";

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
    it("should return Hello World", () => {
      expect(appController.getHello()).toBe("Hello World!");
    });
  });

  describe("health", () => {
    it("should return status ok", () => {
      expect(appController.getHealth()).toEqual({ status: "ok" });
    });
  });
});
