import io
import os
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from PIL import Image
import core
import security as sec
from uploads import save_image
from verification import answers_match


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("CAMPUS_TEST_TEMP"))
        self.old = core.DATA
        core.DATA = Path(self.temp.name)
        core.init_db()
        self.code, self.owner = core.create_owner("registrant")
        self.other_code, self.other = core.create_owner("claimant")

    def tearDown(self):
        core.DATA = self.old
        self.temp.cleanup()

    def item(self, **overrides):
        values = dict(title="지갑", category="지갑", color="검정", description="가죽",
            place="없음", found_at=core.now().isoformat(), storage="보관함", private_hint="안쪽 별 표시")
        values.update(overrides)
        return core.insert("items", values, owner_session=self.owner)

    def test_segment_and_optional_location(self):
        self.assertLess(core.route_distance((35,129.005),[(35,129),(35,129.01)]), .001)
        self.assertAlmostEqual(core.route_distance((35.001,129.005),[(35,129),(35,129.01)]),111.195,delta=.1)
        self.assertEqual(core.route_distance((35,129),[(35,129),(35,129)]),0)
        self.assertEqual(len(core.route_coords(["없음","지행관","없음"])),1)
        self.item()
        self.assertEqual(len(core.search(core.read("items"))),1)
        self.assertTrue(core.search(core.read("items"),route=core.route_coords(["지행관"])).empty)

    def test_codes_legacy_and_modern(self):
        entered = self.code.lower().replace("-", " \n")
        session = core.authenticate_owner(entered, "second-browser")
        self.item()
        self.assertEqual(len(core.owner_items(session)),1)
        with core.connect() as con:
            con.execute("INSERT INTO owners VALUES (?,?)", (core.code_hash("Ab_Cd-Ef123456789"),core.now().isoformat()))
        core.authenticate_owner("Ab_Cd-Ef123456789", "legacy")
        with self.assertRaises(sec.SecurityError):
            core.authenticate_owner("ab_cd-ef123456789", "legacy-bad")

    def test_access_control_session_expiry_and_public_fields(self):
        iid=self.item()
        self.assertNotIn("private_hint",core.read("items").columns)
        self.assertNotIn("storage",core.read("items").columns)
        self.assertTrue(core.owner_items(self.other).empty)
        for bad in (self.code, "invalid", None):
            with self.assertRaises(sec.SecurityError):core.owner_items(bad)
        with self.assertRaises(sec.SecurityError):core.insert("items",{},owner_session=self.other)
        with self.assertRaises(sec.SecurityError):core.read("claims")
        with core.connect() as con:
            con.execute("UPDATE owner_sessions SET expires_at=? WHERE token_hash=?",((core.now()-timedelta(seconds=1)).isoformat(),sec.digest(self.owner)))
        with self.assertRaises(sec.SecurityError):core.owner_items(self.owner)

    def test_authenticated_pickup_atomic_and_replay_blocked(self):
        iid=self.item()
        with self.assertRaises(sec.SecurityError):core.mark_collected(iid)
        with self.assertRaises(sec.SecurityError):core.request_pickup(iid,self.owner,"안쪽에 별 표시")
        rid,otp=core.request_pickup(iid,self.other,"안쪽에 별 표시","감사합니다")
        self.assertTrue(core.pickup_requests(self.other,received=False).storage.isna().all())
        with self.assertRaises(sec.SecurityError):core.approve_ownership(rid,self.other)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)
        core.approve_ownership(rid,self.owner)
        self.assertEqual(core.pickup_requests(self.other,received=False).iloc[0].storage,"보관함")
        self.assertEqual(core.read("items").iloc[0].status,"습득물 등록")
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.other,otp,True)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,False)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,"99999999" if otp!="99999999" else "00000000",True)
        core.complete_pickup(rid,self.owner,otp,True)
        self.assertTrue(core.search(core.read("items")).empty)
        self.assertEqual(core.owner_items(self.owner).iloc[0].pickup_note,"감사합니다")
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)
        self.assertFalse(core.acknowledge_pickup(iid,self.other))
        self.assertTrue(core.acknowledge_pickup(iid,self.owner))

    def test_otp_and_login_limits_persist(self):
        iid=self.item()
        rid,otp=core.request_pickup(iid,self.other,"안쪽의 별 표시")
        core.approve_ownership(rid,self.owner)
        wrong="11111111" if otp!="11111111" else "22222222"
        for _ in range(5):
            with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,wrong,True)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)
        for _ in range(10):
            with self.assertRaises(sec.SecurityError):core.authenticate_owner("wrong-code","attacker")
        with self.assertRaises(sec.SecurityError):core.authenticate_owner(self.code,"attacker")
        with core.connect() as con:
            self.assertGreater(con.execute("SELECT COUNT(*) FROM security_events WHERE outcome='denied'").fetchone()[0],0)
            self.assertNotIn(otp,str(con.execute("SELECT * FROM security_events").fetchall()))

    def test_expired_request_and_rejection(self):
        iid=self.item()
        rid,otp=core.request_pickup(iid,self.other,"안쪽의 별 표시")
        core.approve_ownership(rid,self.owner)
        with core.connect() as con:
            con.execute("UPDATE pickup_requests SET expires_at=? WHERE id=?",((core.now()-timedelta(seconds=1)).isoformat(),rid))
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)
        self.assertTrue(core.pickup_requests(self.other,received=False).storage.isna().all())
        rid,otp=core.request_pickup(iid,self.other,"안쪽의 별 표시")
        with self.assertRaises(sec.SecurityError):core.reject_pickup(rid,self.other)
        core.reject_pickup(rid,self.owner)
        self.assertTrue(core.pickup_requests(self.other,received=False).storage.isna().all())
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)

    def test_injection_bounds_and_csv(self):
        title="=HYPERLINK(\"evil\")"
        self.item(title=title)
        csv=sec.safe_csv(core.read("items")[["title"]]).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK",csv)
        with self.assertRaises(sec.SecurityError):self.item(title="x"*81)
        with self.assertRaises(sec.SecurityError):self.item(category="' OR 1=1--")
        self.assertTrue(core.search(core.read("items"),keywords="' OR 1=1--").empty)

    def test_reports_scoped(self):
        core.insert("reports",dict(title="내 지갑",category="지갑",color="검정",keywords="가죽",start_at=core.now().isoformat(),end_at=core.now().isoformat(),route="[]",radius=100),owner_session=self.owner)
        self.assertEqual(len(core.owner_reports(self.owner)),1)
        self.assertTrue(core.owner_reports(self.other).empty)
        with self.assertRaises(sec.SecurityError):core.read("reports")

    def test_upload_signature_path_and_metadata(self):
        class Upload(io.BytesIO):
            name="wallet.png"
        raw=io.BytesIO();Image.new("RGB",(20,20)).save(raw,"PNG")
        path=save_image(Upload(raw.getvalue()),core.DATA)
        self.assertIsNotNone(sec.image_path(core.DATA,path))
        self.assertIsNone(sec.image_path(core.DATA,"../../secrets.txt"))
        with self.assertRaises(sec.SecurityError):save_image(Upload(b"<script>bad</script>"),core.DATA)
        with Image.open(core.DATA/path) as im:
            self.assertFalse(im.getexif())

    def test_local_recovery_does_not_reassign_existing(self):
        from recover_registration import recover
        iid=self.item()
        with self.assertRaises(ValueError):recover([iid])
        with core.connect() as con:
            legacy=con.execute("INSERT INTO items(title,category,color,description,place,found_at,storage) VALUES ('legacy','지갑','검정','가죽','없음',?,'보관함')",(core.now().isoformat(),)).lastrowid
        path=recover([legacy])
        code=path.read_text(encoding="utf-8").split("확인 코드:\n")[1].splitlines()[0]
        session=core.authenticate_owner(code,"recovery")
        self.assertEqual(core.owner_items(session).iloc[0].id,legacy)
        self.assertEqual(len(core.owner_items(self.owner)),1)

    def test_demo_photos_label_and_idempotence(self):
        from demo_photos import install_demo_photos
        self.item(title="검정 반지갑")
        self.assertEqual(install_demo_photos(),1)
        self.assertEqual(install_demo_photos(),0)
        item=core.read("items").iloc[0]
        self.assertEqual(item.is_demo_image,1)
        self.assertIsNotNone(sec.image_path(core.DATA,item.image))

    def test_synonymous_answers_and_conflicts(self):
        q="지갑 안쪽에는 어떤 모양의 표시가 있나요?"
        for expected, answer in [("안쪽에 별 모양 있어요","내부 별 모양"), ("내부 별 모양","안쪽에 별 모양 있어요"),
                                 ("안쪽 별 표시","별"), ("별","내부 별 모양"), ("데모 확인 특징: 안쪽에 별 표시","내부 별 모양"),
                                 ("내부 하트 무늬","안쪽에 하트 그림이 있어요")]:
            self.assertTrue(answers_match(expected,answer,q),(expected,answer))
        for answer in ["안쪽에 하트 모양", "안쪽 별 모양 없어요", "내부 별이 아니에요", "외부 별 모양", "별 하트 세모 네모", "모르겠어요"]:
            self.assertFalse(answers_match("안쪽 별 모양",answer,q),answer)
        self.assertTrue(answers_match("검정","검은색","무슨 색인가요?"))
        self.assertFalse(answers_match("안쪽 별 모양","전혀 다른 표현",q))

    def test_flexible_colours_materials_and_literal_answers(self):
        positives=[
            ("진한 빨간색","빨강","안쪽 라벨은 무슨 색인가요?"),
            ("짙은 빨간색","붉은색이에요","안쪽 색상은?"),
            ("연한 파란색","blue","스티커 색깔은?"),
            ("천연 가죽","레더 재질입니다","안쪽 소재는 무엇인가요?"),
            ("고양이","야옹이 그림이 있어요","라벨에는 어떤 동물이 있나요?"),
            ("안쪽 하트 스티커","내부에 하트 모양이 붙어 있어요","안쪽에는 어떤 스티커가 있나요?"),
            ("민수","이름은 민수라고 적혀있어요","라벨에 적힌 이름은?"),
            ("JK","J K 입니다","영문 이니셜은?"),
            ("17","십칠","안쪽 숫자는?"),
            ("20","이십","안쪽 번호는?"),
            ("일곱","7번","안쪽 숫자는?"),
            ("은색 동그라미 각인","실버 원형이 새겨져 있어요","손잡이에는 어떤 표시가 있나요?"),
            ("무궁화","무궁화입니다","어떤 문양인가요?"),
            ("별 | 달","달 모양","어떤 모양인가요?"),
        ]
        for expected,given,question in positives:
            self.assertTrue(answers_match(expected,given,question),(expected,given,question))
        for expected,given,question in [("진한 빨간색","파랑","안쪽 색은?"),("민수","민서","이름은?"),
            ("이민수","민수","이름은?"),("17","18","번호는?"),("JK","JL","이니셜은?"),
            ("고양이","강아지","동물은?"),("빨강","빨강 또는 파랑","색상은?")]:
            self.assertFalse(answers_match(expected,given,question),(expected,given))

    def test_auto_verification_and_pending_retry(self):
        iid=self.item(verification_question="지갑 안쪽에는 어떤 모양의 표시가 있나요?")
        self.assertNotIn("private_hint",core.read("items").columns)
        rid,old_otp=core.request_pickup(iid,self.other,"내부 하트 모양")
        self.assertTrue(core.pickup_requests(self.other,False).storage.isna().all())
        updated,otp=core.request_pickup(iid,self.other,"안쪽에 별 모양 있어요")
        self.assertEqual(updated,rid)
        result=core.pickup_requests(self.other,False).iloc[0]
        self.assertEqual(result.status,"소유 확인 완료")
        self.assertEqual(result.storage,"보관함")
        self.assertTrue(core.pickup_requests(self.owner,False).empty)
        self.assertEqual(core.read("items").iloc[0].status,"습득물 등록")
        core.complete_pickup(rid,self.owner,otp,True)
        self.assertEqual(core.read("items").iloc[0].status,"반환 완료")

    def test_score_breakdown_and_active_maximum(self):
        self.item(description="가죽 은색 로고")
        items=core.read("items")
        items["lat"]=35.0;items["lon"]=129.0
        result=core.search(items,"지갑","검정","가죽 은색",[(35.0,129.0)],100,strict=False)
        self.assertEqual(result.iloc[0].score,100)
        self.assertEqual(result.attrs["score_max"],100)
        self.assertEqual(result.iloc[0][["category_score","color_score","keyword_score","location_score"]].sum(),100)
        result=core.search(items,"지갑","검정","가죽 은색",strict=False)
        self.assertEqual(result.iloc[0].score,80)
        self.assertEqual(result.attrs["score_max"],80)
        result=core.search(items,"지갑","검정",strict=False)
        self.assertEqual(result.iloc[0].score,60)
        self.assertEqual(result.attrs["score_max"],60)

    def test_report_deletion_is_owner_scoped_and_does_not_remove_items(self):
        values=dict(title="내 분실 신고",category="지갑",color="검정",keywords="가죽",
                    start_at=core.now().isoformat(),end_at=core.now().isoformat(),route="[]",radius=100)
        rid=core.insert("reports",values,owner_session=self.owner)
        other=core.insert("reports",values,owner_session=self.other)
        iid=self.item()
        with self.assertRaises(sec.SecurityError):core.delete_report(rid,self.other)
        with self.assertRaises(sec.SecurityError):core.delete_report(rid,"invalid-session")
        self.assertEqual(len(core.owner_reports(self.owner)),1)
        core.delete_report(rid,self.owner)
        self.assertTrue(core.owner_reports(self.owner).empty)
        self.assertEqual(core.owner_reports(self.other).iloc[0].id,other)
        self.assertEqual(core.read("items").iloc[0].id,iid)
        with self.assertRaises(sec.SecurityError):core.delete_report(rid,self.owner)
        with core.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM report_owners WHERE report_id=?",(rid,)).fetchone()[0],0)

    def test_real_local_ai_handles_unlisted_sentence(self):
        from semantic_ai import judge_answer
        result=judge_answer("지퍼가 고장났어요","잠금 장치가 잘 안 닫혀요","어떤 고장이 있나요?")
        self.assertTrue(result["passed"])
        self.assertEqual(result["engine"],"local-minilm-onnx")
        self.assertGreaterEqual(result["score"],result["threshold"])
        self.assertFalse(judge_answer("무궁화","장미","어떤 문양인가요?")["passed"])

    def test_ai_failure_does_not_disclose_location(self):
        from unittest.mock import patch
        from semantic_ai import ModelUnavailable
        iid=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        with patch("semantic_ai.get_model",side_effect=ModelUnavailable("unavailable")):
            rid,_=core.request_pickup(iid,self.other,"안쪽 별 모양")
        row=core.pickup_requests(self.other,False).iloc[0]
        self.assertEqual(row.verification_engine,"unavailable")
        self.assertEqual(row.status,"확인 대기")
        self.assertTrue(__import__("pandas").isna(row.storage))

    def test_picture_description_suffixes_keep_the_same_feature(self):
        from semantic_ai import judge_answer
        for answer in ("하늘사진","하늘 사진","하늘 사진이에요","하늘 사진이요","하늘 이미지"):
            with self.subTest(answer=answer):
                self.assertTrue(judge_answer("하늘",answer,"안쪽에는 어떤 사진이 있나요?")["passed"])
        self.assertFalse(judge_answer("하늘","바다 사진","안쪽에는 어떤 사진이 있나요?")["passed"])
        self.assertFalse(judge_answer("하늘","하늘사진","적힌 이름은 무엇인가요?")["passed"])
        iid=self.item(private_hint="하늘",verification_question="어떤 사진이 있나요?")
        core.request_pickup(iid,self.other,"하늘사진")
        row=core.pickup_requests(self.other,False).iloc[0]
        self.assertEqual(row.status,"소유 확인 완료")
        self.assertEqual(row.storage,"보관함")

    def test_opposite_states_and_quantities_cannot_auto_approve(self):
        from semantic_ai import judge_answer
        for expected,answer in (
            ("지퍼가 안 닫혀요","지퍼가 닫혀요"),
            ("지퍼가 닫히지 않아요","지퍼가 닫혀요"),
            ("스티커가 붙어 있어요","스티커가 떨어졌어요"),
            ("스티커가 안 떨어져요","스티커가 떨어졌어요"),
            ("스티커가 떨어지지 않아요","스티커가 떨어졌어요"),
            ("지퍼 고장","지퍼는 정상입니다"),
            ("지퍼는 정상이 아님","지퍼는 정상입니다"),
            ("별 표시 없고 지퍼 고장","별 표시 있고 지퍼 고장"),
            ("열쇠 두 개","열쇠 세 개"),
        ):
            with self.subTest(expected=expected,answer=answer):
                self.assertFalse(judge_answer(expected,answer,"어떤 특징이 있나요?")["passed"])
                self.assertFalse(judge_answer(answer,expected,"어떤 특징이 있나요?")["passed"])
        self.assertTrue(judge_answer("진한 빨간색","빨강","안쪽 색상은?")["passed"])
        self.assertTrue(judge_answer("지퍼가 고장났어요","지퍼가 닫히지 않아요","어떤 고장이 있나요?")["passed"])
        iid=self.item(private_hint="지퍼가 안 닫혀요",verification_question="어떤 고장이 있나요?")
        core.request_pickup(iid,self.other,"지퍼가 닫혀요")
        row=core.pickup_requests(self.other,False).iloc[0]
        self.assertEqual(row.status,"확인 대기")
        self.assertTrue(__import__("pandas").isna(row.storage))

    def test_physical_states_and_precise_numbers_reject_but_aliases_pass(self):
        from semantic_ai import judge_answer
        negatives=[
            ("지퍼가 닫혀 있어요","지퍼가 열려 있어요","지퍼 상태는 어떤가요?"),
            ("닫힌 지퍼","열린 지퍼","지퍼 상태는?"),
            ("1.7","17","적힌 숫자는 무엇인가요?"),
            ("-17","17","적힌 번호는?"),
            ("열쇠 열한 개","열쇠 한 개","안에 무엇이 있나요?"),
            ("열쇠스물한개","열쇠한개","안에 무엇이 있나요?"),
            ("사진 12장","사진 2장","안쪽 특징은?"),
            ("이장","2장","안쪽에 적힌 이름은?"),
        ]
        for expected,answer,q in negatives:
            with self.subTest(expected=expected,answer=answer):
                self.assertFalse(judge_answer(expected,answer,q)["passed"])
                self.assertFalse(judge_answer(answer,expected,q)["passed"])
        for expected,answer,q in (
            ("하늘","하늘사진","어떤 사진이 있나요?"),
            ("하늘 사진","하늘 사진이에요","안쪽 특징은?"),
            ("진한 빨간색","빨강","무슨 색인가요?"),
            ("닫혀 있어요","닫힌 상태입니다","지퍼 상태는?"),
            ("열려 있어요","열린 상태입니다","지퍼 상태는?"),
            ("1.7","1.70","적힌 숫자는?"),
            ("열한 개","11","몇 개인가요?"),
            ("열쇠 열한 개","열쇠 11개","안에 무엇이 있나요?"),
            ("열쇠스물한개","열쇠21개","안에 무엇이 있나요?"),
            ("열쇠 십일 개","열쇠 11개","안에 무엇이 있나요?"),
        ):
            with self.subTest(expected=expected,answer=answer):
                self.assertTrue(judge_answer(expected,answer,q)["passed"])
        for expected,answer,q in negatives[:3]:
            iid=self.item(private_hint=expected,verification_question=q)
            core.request_pickup(iid,self.other,answer)
        rows=core.pickup_requests(self.other,False)
        self.assertTrue(rows.status.eq("확인 대기").all())
        self.assertTrue(rows.storage.isna().all())

    def test_inference_does_not_block_another_users_registration(self):
        from unittest.mock import patch
        iid=self.item(verification_question="안쪽 특징은?")
        def judge(*args):
            # This write would time out if inference still held SQLite's writer lock.
            self.item(title="다른 사용자 등록")
            return dict(passed=True,score=1.,engine="review-test",reason="test")
        with patch.object(core,"judge_answer",side_effect=judge):
            core.request_pickup(iid,self.other,"별 모양")
        self.assertEqual(len(core.read("items")),2)
        self.assertEqual(core.pickup_requests(self.other,False).iloc[0].status,"소유 확인 완료")

    def test_inference_rechecks_item_and_pending_approval_before_saving(self):
        from unittest.mock import patch
        iid=self.item(verification_question="안쪽 특징은?")
        def change_item(*args):
            with core.connect() as con:
                con.execute("UPDATE items SET private_hint='다른 정답' WHERE id=?",(iid,))
            return dict(passed=True,score=1.,engine="test",reason="test")
        with patch.object(core,"judge_answer",side_effect=change_item):
            with self.assertRaises(sec.SecurityError):core.request_pickup(iid,self.other,"별")
        self.assertTrue(core.pickup_requests(self.other,False).empty)
        # An owner's manual decision made during inference must not be overwritten.
        with patch.object(core,"judge_answer",return_value=dict(passed=False,score=0.,engine="test",reason="test")):
            rid,otp=core.request_pickup(iid,self.other,"이전 답변")
        def approve_pending(*args):
            core.approve_ownership(rid,self.owner)
            return dict(passed=False,score=0.,engine="test",reason="test")
        with patch.object(core,"judge_answer",side_effect=approve_pending):
            with self.assertRaises(sec.SecurityError):core.request_pickup(iid,self.other,"새 답변")
        current=core.pickup_requests(self.other,False).iloc[0]
        self.assertEqual(current.status,"소유 확인 완료")
        self.assertEqual(current.evidence,"이전 답변")
        core.complete_pickup(rid,self.owner,otp,True)

    def test_concurrent_proofs_save_only_one_active_approval(self):
        import threading
        from unittest.mock import patch
        iid=self.item(verification_question="안쪽 특징은?")
        barrier=threading.Barrier(2,timeout=4)
        successes=[];failures=[]
        def judge(*args):
            barrier.wait()
            return dict(passed=True,score=1.,engine="test",reason="test")
        def request():
            try:successes.append(core.request_pickup(iid,self.other,"별"))
            except Exception as exc:failures.append(exc)
        with patch.object(core,"judge_answer",side_effect=judge):
            threads=[threading.Thread(target=request) for _ in range(2)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(8)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(successes),1)
        self.assertEqual(len(failures),1)
        self.assertIsInstance(failures[0],sec.SecurityError)
        self.assertEqual(len(core.pickup_requests(self.other,False)),1)

    def test_attempts_survive_inference_failure_and_session_is_rechecked(self):
        from unittest.mock import patch
        iid=self.item(verification_question="안쪽 특징은?")
        with patch.object(core,"judge_answer",side_effect=RuntimeError("test inference failure")):
            for _ in range(5):
                with self.assertRaises(RuntimeError):core.request_pickup(iid,self.other,"별")
            with self.assertRaises(sec.SecurityError):core.request_pickup(iid,self.other,"별")
        self.assertTrue(core.pickup_requests(self.other,False).empty)
        other_item=self.item(verification_question="안쪽 특징은?")
        def expire(*args):
            with core.connect() as con:
                con.execute("UPDATE owner_sessions SET expires_at=? WHERE token_hash=?",
                            ((core.now()-timedelta(seconds=1)).isoformat(),sec.digest(self.other)))
            return dict(passed=True,score=1.,engine="test",reason="test")
        with patch.object(core,"judge_answer",side_effect=expire):
            with self.assertRaises(sec.SecurityError):core.request_pickup(other_item,self.other,"별")

    def test_otp_renewal_recovers_from_lockout_and_invalidates_old_code(self):
        iid=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        rid,old=core.request_pickup(iid,self.other,"내부 별 모양")
        wrong="11111111" if old!="11111111" else "22222222"
        for _ in range(5):
            with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,wrong,True)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,old,True)
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,self.owner)
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,"invalid")
        before=core.pickup_requests(self.other,False).iloc[0].expires_at
        new=core.renew_pickup_otp(rid,self.other)
        self.assertNotEqual(old,new)
        self.assertEqual(core.pickup_requests(self.other,False).iloc[0].expires_at,before)
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,old,True)
        core.complete_pickup(rid,self.owner,new,True)
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,self.other)
        self.assertEqual(core.owner_items(self.owner).iloc[0].status,"반환 완료")

    def test_otp_renewal_requires_live_approval_and_is_rate_limited(self):
        iid=self.item()
        rid,_=core.request_pickup(iid,self.other,"내부 별 모양")
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,self.other)
        core.approve_ownership(rid,self.owner)
        for _ in range(3):core.renew_pickup_otp(rid,self.other)
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,self.other)
        with core.connect() as con:
            con.execute("UPDATE pickup_requests SET expires_at=? WHERE id=?",((core.now()-timedelta(seconds=1)).isoformat(),rid))
        with self.assertRaises(sec.SecurityError):core.renew_pickup_otp(rid,self.other)

    def test_rotation_during_completion_rejects_stale_otp(self):
        from unittest.mock import patch
        iid=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        rid,old=core.request_pickup(iid,self.other,"내부 별 모양")
        same=sec.same
        rotated=[]
        def rotate_then_compare(a,b):
            if not rotated:
                rotated.append(True)
                core.renew_pickup_otp(rid,self.other)
            return same(a,b)
        with patch.object(sec,"same",side_effect=rotate_then_compare):
            with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,old,True)
        self.assertNotEqual(core.read("items").iloc[0].status,"반환 완료")

    def test_policy_upgrade_pauses_old_live_auto_approvals_only_once(self):
        auto=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        rid,otp=core.request_pickup(auto,self.other,"내부 별 모양")
        manual=self.item()
        manual_rid,_=core.request_pickup(manual,self.other,"내부 별 모양")
        core.approve_ownership(manual_rid,self.owner)
        completed=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        completed_rid,code=core.request_pickup(completed,self.other,"내부 별 모양")
        core.complete_pickup(completed_rid,self.owner,code,True)
        with core.connect() as con:
            con.execute("DELETE FROM app_metadata WHERE key='answer_policy'")
        core.init_db()
        records=core.pickup_requests(self.other,False).set_index("id")
        self.assertEqual(records.loc[rid,"status"],"확인 대기")
        self.assertTrue(__import__("pandas").isna(records.loc[rid,"storage"]))
        self.assertEqual(records.loc[manual_rid,"status"],"소유 확인 완료")
        self.assertEqual(records.loc[completed_rid,"status"],"반환 완료")
        with self.assertRaises(sec.SecurityError):core.complete_pickup(rid,self.owner,otp,True)
        core.approve_ownership(rid,self.owner)
        core.init_db()
        self.assertEqual(core.pickup_requests(self.other,False).set_index("id").loc[rid,"status"],"소유 확인 완료")

    def test_recipient_can_confirm_actual_collection_only_after_verification(self):
        iid=self.item(verification_question="안쪽에는 어떤 표시가 있나요?")
        rid,otp=core.request_pickup(iid,self.other,"내부 별 모양")
        with self.assertRaises(sec.SecurityError):core.confirm_received(rid,self.owner,otp,True)
        with self.assertRaises(sec.SecurityError):core.confirm_received(rid,self.other,otp,False)
        wrong="99999999" if otp!="99999999" else "11111111"
        with self.assertRaises(sec.SecurityError):core.confirm_received(rid,self.other,wrong,True)
        core.confirm_received(rid,self.other,otp,True)
        self.assertTrue(core.search(core.read("items")).empty)
        self.assertEqual(core.owner_items(self.owner).iloc[0].status,"반환 완료")
        with self.assertRaises(sec.SecurityError):core.confirm_received(rid,self.other,otp,True)

    def test_coordinate_sync_updates_legacy_item(self):
        iid=self.item(place="의생명과학도서관")
        with core.connect() as con:
            con.execute("UPDATE items SET lat=35.3172,lon=129.005 WHERE id=?",(iid,))
            con.execute("DELETE FROM app_metadata WHERE key='place_coordinates'")
        core.init_db()
        row=core.read("items").iloc[0];place=core.places().loc["의생명과학도서관"]
        self.assertAlmostEqual(row.lat,place.lat)
        self.assertAlmostEqual(row.lon,place.lon)
        self.assertGreater(row.lat,35.326)
        self.assertTrue((core.DATA/"campus-before-coordinate-update.db").exists())

    def test_extra_examples_preserve_user_items_and_completion(self):
        from demo_data import add_examples
        iid=self.item(title="개인 등록물")
        self.assertEqual(add_examples(),20)
        self.assertEqual(add_examples(),0)
        self.assertEqual(len(core.read("items")),21)
        with core.connect() as con:
            demo=con.execute("SELECT id FROM items WHERE demo_key IS NOT NULL LIMIT 1").fetchone()[0]
            con.execute("UPDATE items SET status='반환 완료' WHERE id=?",(demo,))
        self.assertEqual(add_examples(),0)
        self.assertEqual(len(core.search(core.read("items"))),20)
        self.assertEqual(core.read("items").set_index("id").loc[iid,"title"],"개인 등록물")

    def test_distinct_demo_photos_sync_preserves_real_uploads_and_status(self):
        import hashlib
        import json
        import shutil
        from demo_data import add_examples,refresh_example_assets
        add_examples()
        rows=core.read("items")
        self.assertEqual(len(rows),24)
        self.assertEqual(len({hashlib.sha256(sec.image_path(core.DATA,r.image).read_bytes()).hexdigest() for r in rows.itertuples()}),24)
        examples=json.loads((core.BASE/"assets/demo_items.json").read_text(encoding="utf-8"))
        with core.connect() as con:
            first=con.execute("SELECT id,image,private_hint FROM items WHERE demo_key=?",(examples[0]["key"],)).fetchone()
            second=con.execute("SELECT id,image FROM items WHERE demo_key=?",(examples[1]["key"],)).fetchone()
            con.execute("UPDATE items SET status='반환 완료',title='old demo',color='기타' WHERE id=?",(first[0],))
            con.execute("UPDATE items SET is_demo_image=0,title='실제 사진으로 교체함' WHERE id=?",(second[0],))
        shutil.copyfile(core.BASE/"assets/demo_photos/wallet.jpg",core.DATA/first[1])
        real_bytes=(core.DATA/second[1]).read_bytes()
        self.assertEqual(refresh_example_assets(),1)
        with core.connect() as con:
            current=con.execute("SELECT status,title,color,private_hint FROM items WHERE id=?",(first[0],)).fetchone()
        self.assertEqual(current,("반환 완료",examples[0]["title"],examples[0]["color"],first[2]))
        self.assertEqual((core.DATA/second[1]).read_bytes(),real_bytes)
        self.assertEqual(core.read("items").set_index("id").loc[second[0],"title"],"실제 사진으로 교체함")
        self.assertEqual(refresh_example_assets(),0)


if __name__=="__main__":unittest.main()
