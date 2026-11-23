// Own synthetic frozen inputs. No historical payloads or scientific fits.
const profiles = ['figure-landscape', 'a4-landscape', 'a4-portrait'];
function record(rows=3) {
  return {schema_version:'pgv.passport_history/1', snapshot_ref:'rs-typo-independent-start',
    session_snapshot_id:'physical-start',artifact_id:'artifact-typo-start',stage:'start',universe:'single',
    content_status:'present',content_gap_reason:null,
    passport:{basic_stats:{n:37,mean:7.25},freq:{label:'месяц'},
      certificate_group:Object.fromEntries(Array.from({length:rows},(_,i)=>['metric_'+i, 'БЕРЁЗА КИРИЛЛИЦА '+i]))},
    target_column:'Показатель',date_column:'Месяц',context_id:'ctx-independent-typography',data_revision:'3',
    captured_at:'2026-11-23T10:00:00Z',created_at:'2026-11-23T10:00:00Z',
    fingerprint:'f'.repeat(64),fingerprint_reason:null,source_hash:'a'.repeat(64),source_hash_reason:null,
    passport_schema_version:'passport/1.2',passport_schema_version_reason:null,
    calculation_version:'independent-fixture/1',calculation_version_reason:null};
}
function comparison() {
  return {schema_version:'pgv.passport_comparison/1',mode:'explicit',run_id:'RUN-TYPO-INDEPENDENT',
    ordered_refs:['rs-start','rs-exit'],path:['start','exit'],
    comparisons:[{from_stage:'start',to_stage:'exit',comparison:{
      metrics:{n:{v_old:37,v_new:37,delta:0,delta_pct:0},mean:{v_old:1,v_new:8,delta:7,delta_pct:700}},
      qualitative_changes:['Кириллица сохранена; знак изменения не означает статистическую значимость.'],
      categorical_changes:{},list_changes:{},boolean_changes:{},summary:'Сравнение сохранённых значений'}}],
    confirmation:null,checkpoint:null,context:{context_id:'ctx-independent-typography',data_revision:'3'},
    cross_context:false,aliases:[],method_versions:{engine:{id:'independent',version:'1'},records:[]},
    definitions:{delta:'Абсолютное изменение сохранённых значений.',percent:'Относительное изменение; при нуле основания не определено.'},
    gaps:[],completeness:'complete'};
}
function payload(profile,kind='p01',rows=3) {
  return {schema_version:'pgv.render_payload/1',request_id:'typo-'+profile+'-'+kind+'-'+rows,
    snapshot:{schema_version:'pgv.visual_print_snapshot/1',view_id:'passport.independent',scope:'research',
      refs:{research_run_id:'RUN-TYPO-INDEPENDENT',data_revision:'3'},
      result:{result_ref:'independent-fixed-result',result_schema_version:'pgv.visual_result/1',result_digest:'fixture',result_digest_reason:null},
      data_artifact:{artifact_id:null,artifact_version:'3',source_hash:null,hash_algorithm:null,hash_reason:'synthetic-fixture'},
      expected_context:{context_id:'ctx-independent-typography',data_revision:'3',expected_data_digest:null},
      dimensions:{target_column:'Показатель',date_column:'Месяц',entity_column:null,entity_id:null,mode:'univariate'},
      times:{computed_at:null,computed_at_reason:'fixture',captured_at:'2026-11-23T10:00:00Z',captured_at_reason:null,
        checkpoint_confirmed_at:null,render_requested_at:'2026-11-23T10:00:00Z',timezone:'UTC',locale:'ru-RU'},
      display:{title:'Независимая проверка физической типографики',subtitle:null,detail_level:'compact',sections:[]},
      checkpoint:null,method:{origin:'producer_freeze',method:'independent-fixed-input',parameters:{}},
      sampling:{applicable:false,mode:null,point_cap:null,reason:'full-saved-document'},
      selection:{allowlist:[],values:{}},annotations:{revision:0,author:'analyst',text:null},
      print:{profile_id:profile,page_count:1,theme:'light-print'},
      renderer_env:{renderer_version:'print-renderer/1',font_profile:'print-fonts-dejavu/1',dependency_status:'available',unavailable_reason:null},
      data_flow:{before_revision:null,after_revision:null},sensitive:{raw_data_included:false,sensitive_fields_policy:'metadata_only'},
      warnings:[],documents:{print_kind:kind==='p01'?'P01':'P02'}},
    sections:[kind==='p01'?{section_id:'independent-p01',kind:'passport_record',record:record(rows)}:
      {section_id:'independent-p02',kind:'passport_comparison',comparison:comparison()}]};
}
module.exports={profiles,payload,record,comparison};
